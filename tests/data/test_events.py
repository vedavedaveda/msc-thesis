import pandas as pd
from google.genai import errors

from msc_thesis.data.events.cleaning import events_from_setlists
from msc_thesis.data.events.enrichment import (
    EventConfidence,
    EventEnricher,
    EventEnrichment,
)
from msc_thesis.data.events.ingestion import SetlistFMEventSource


def test_setlistfm_event_source_fetches_multiple_pages(monkeypatch):
    class DummyResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    responses = {
        1: DummyResponse({"setlist": [{"id": "1"}, {"id": "2"}]}),
        2: DummyResponse({"setlist": [{"id": "3"}]}),
    }

    def fake_get(url, headers=None, params=None, timeout=30):
        page = params["p"]
        return responses[page]

    monkeypatch.setattr(
        "msc_thesis.data.events.ingestion.requests.get",
        fake_get,
    )

    source = SetlistFMEventSource(api_key="demo-key", sleep_seconds=0)
    data = source.fetch_events(
        country_code="DK",
        state="Capital Region",
        year=2019,
        per_page=2,
        max_pages=2,
    )

    assert len(data["setlist"]) == 3
    assert data["setlist"][0]["id"] == "1"
    assert data["setlist"][2]["id"] == "3"


def test_events_from_setlists_creates_dataframe_like_records():
    raw = {
        "setlist": [
            {
                "artist": {"name": "Artist A", "mbid": "mbid-1", "url": "https://example.com/a"},
                "venue": {
                    "name": "Venue A",
                    "id": "venue-1",
                    "url": "https://example.com/v1",
                    "city": {
                        "name": "Copenhagen",
                        "coords": {"lat": 55.6761, "long": 12.5683},
                        "country": {"name": "Denmark", "code": "DK"},
                    },
                },
                "eventDate": "15-06-2019",
                "tour": {"name": "Tour A"},
                "info": "A note",
                "id": "set-1",
                "url": "https://example.com/set-1",
                "lastUpdated": "2019-06-15",
            }
        ]
    }

    events_df = events_from_setlists(raw)

    assert len(events_df) == 1
    assert events_df.iloc[0]["event_name"] == "Artist A @ Venue A"
    assert events_df.iloc[0]["city"] == "Copenhagen"
    assert events_df.iloc[0]["country_code"] == "DK"
    assert events_df.iloc[0]["latitude"] == 55.6761


def test_event_enricher_uses_structured_response_schema():
    class DummyModels:
        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return type("Response", (), {"parsed": "parsed result"})()

    class DummyClient:
        def __init__(self):
            self.models = DummyModels()

    client = DummyClient()
    enricher = EventEnricher(client=client)

    result = enricher.enrich_event(
        {"event_name": "Artist A @ Venue A", "artist_name": "Artist A"}
    )

    assert result == "parsed result"
    assert client.models.kwargs["model"] == enricher.models[0] == "gemini-3.6-flash"
    assert client.models.kwargs["config"].response_schema.__name__ == "EventEnrichment"
    assert "Artist A @ Venue A" in client.models.kwargs["contents"]


def test_event_enricher_retries_rate_limit_then_succeeds():
    class DummyModels:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise errors.APIError(429, {"message": "rate limited"})
            return type("Response", (), {"parsed": "parsed result"})()

    class DummyClient:
        def __init__(self):
            self.models = DummyModels()

    delays = []
    client = DummyClient()
    enricher = EventEnricher(
        client=client,
        retry_delay_seconds=2,
        sleep_fn=delays.append,
    )

    result = enricher.enrich_event({"event_name": "Artist @ Venue"})

    assert result == "parsed result"
    assert client.models.calls == 3
    assert delays == [2, 4]


def test_event_enricher_uses_fallback_model_after_primary_rate_limit():
    class DummyModels:
        def __init__(self):
            self.models = []

        def generate_content(self, **kwargs):
            self.models.append(kwargs["model"])
            if kwargs["model"] == "primary-model":
                raise errors.APIError(429, {"message": "rate limited"})
            return type("Response", (), {"parsed": "fallback result"})()

    class DummyClient:
        def __init__(self):
            self.models = DummyModels()

    client = DummyClient()
    enricher = EventEnricher(
        client=client,
        models=("primary-model", "fallback-model", "last-resort-model"),
        max_retries=1,
        retry_delay_seconds=0,
        sleep_fn=lambda _: None,
    )

    result = enricher.enrich_event({"event_name": "Artist @ Venue"})

    assert result == "fallback result"
    assert client.models.models == [
        "primary-model",
        "primary-model",
        "fallback-model",
    ]


def test_event_enricher_updates_source_and_saves_batch_results(tmp_path):
    confidence = EventConfidence(**{name: 0.9 for name in EventConfidence.model_fields})
    parsed_result = EventEnrichment(
        event_type="concert",
        event_subtype="club_concert",
        doors_time=None,
        start_time=None,
        end_time=None,
        venue_capacity=None,
        expected_attendance=None,
        actual_attendance=None,
        sold_out=None,
        indoor_outdoor="unknown",
        audience_draw="unknown",
        confidence=confidence,
    )

    class DummyModels:
        calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            return type("Response", (), {"parsed": parsed_result})()

    class DummyClient:
        def __init__(self):
            self.models = DummyModels()

    client = DummyClient()
    enricher = EventEnricher(client=client)
    events_df = pd.DataFrame(
        [
            {"setlist_id": "one", "event_name": "Artist One @ Venue"},
            {"setlist_id": "two", "event_name": "Artist Two @ Venue"},
        ]
    )
    source_path = tmp_path / "events.csv"
    output_path = tmp_path / "event_enrichments.csv"
    events_df.to_csv(source_path, index=False)

    enriched_df = enricher.enrich_dataframe(
        events_df,
        source_csv_path=source_path,
        enriched_output_path=output_path,
        sleep_seconds=0,
    )

    assert client.models.calls == 2
    assert enriched_df["event_type"].tolist() == ["concert", "concert"]
    assert enriched_df["confidence_event_type"].tolist() == [0.9, 0.9]
    assert len(pd.read_csv(output_path)) == 2
    assert pd.read_csv(source_path)["enriched"].tolist() == [True, True]

    enricher.enrich_dataframe(
        events_df,
        source_csv_path=source_path,
        enriched_output_path=output_path,
        sleep_seconds=0,
    )
    assert client.models.calls == 2
