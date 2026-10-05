import os
import time
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

from google import genai
from google.genai import errors
from google.genai import types
import httpx
import pandas as pd
from pydantic import BaseModel, Field


class EventConfidence(BaseModel):
    event_type: float = Field(ge=0.0, le=1.0)
    event_subtype: float = Field(ge=0.0, le=1.0)
    doors_time: float = Field(ge=0.0, le=1.0)
    start_time: float = Field(ge=0.0, le=1.0)
    end_time: float = Field(ge=0.0, le=1.0)
    venue_capacity: float = Field(ge=0.0, le=1.0)
    expected_attendance: float = Field(ge=0.0, le=1.0)
    actual_attendance: float = Field(ge=0.0, le=1.0)
    sold_out: float = Field(ge=0.0, le=1.0)
    indoor_outdoor: float = Field(ge=0.0, le=1.0)
    audience_draw: float = Field(ge=0.0, le=1.0)


class EventEnrichment(BaseModel):
    event_type: Literal["concert", "music_festival", "other"]
    event_subtype: Literal[
        "club_concert",
        "theatre_concert",
        "arena_concert",
        "stadium_concert",
        "outdoor_concert",
        "music_festival",
        "other",
    ]
    doors_time: str | None
    start_time: str | None
    end_time: str | None
    venue_capacity: int | None
    expected_attendance: int | None
    actual_attendance: int | None
    sold_out: bool | None
    indoor_outdoor: Literal["indoor", "outdoor", "mixed", "unknown"]
    audience_draw: Literal[
        "local",
        "regional",
        "national",
        "international",
        "unknown",
    ]
    confidence: EventConfidence


class EventEnricher:
    """Use Gemini to enrich structured music-event records."""

    def __init__(
        self,
        api_key: str | None = None,
        models: Sequence[str] | None = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 2.0,
        max_retry_delay_seconds: float = 30.0,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if client is None:
            resolved_api_key = api_key or os.getenv("GEMINI_API_KEY")
            if not resolved_api_key:
                raise ValueError(
                    "Missing GEMINI_API_KEY. Pass api_key or set the environment variable."
                )
            client = genai.Client(api_key=resolved_api_key)

        self.client = client
        self.models = tuple(models or ("gemini-3.6-flash",))
        if not self.models or any(not model_name.strip() for model_name in self.models):
            raise ValueError("models must contain at least one non-empty model name.")
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self.sleep_fn = sleep_fn

    @staticmethod
    def build_prompt(row: Mapping[str, Any]) -> str:
        return f"""
You are enriching a structured dataset of music events for a
public-transport forecasting research project.

Event:
- Event name: {row.get("event_name")}
- Artist: {row.get("artist_name")}
- Date: {row.get("event_date")}
- Venue: {row.get("venue_name")}
- City: {row.get("city")}
- Country: {row.get("country")}
- Setlist.fm URL: {row.get("setlist_url")}

Extract the requested structured information.

Rules:
- Do not invent facts.
- If a value cannot be determined reliably, return null or "unknown".
- Times must use 24-hour HH:MM format.
- Attendance and capacity must be integers.
- expected_attendance means expected before the event.
- actual_attendance means reported after the event.
- If sold-out status is unknown, return null, not false.

For audience_draw:
- local: mainly immediate city/local area
- regional: surrounding region
- national: attracts people from across Denmark
- international: meaningful international audience

For event_subtype, classify the physical event format/scale,
not merely the popularity of the artist.
"""

    def enrich_event(self, row: Mapping[str, Any]) -> EventEnrichment:
        last_error: Exception | None = None
        for model_index, model_name in enumerate(self.models):
            for attempt in range(self.max_retries + 1):
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=self.build_prompt(row),
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=EventEnrichment,
                        ),
                    )
                    if response.parsed is None:
                        raise ValueError(
                            "Gemini returned no parsed event-enrichment result."
                        )
                    return response.parsed
                except (errors.APIError, httpx.TransportError, TimeoutError, ConnectionError) as exc:
                    last_error = exc
                    can_retry = self._is_retryable(exc)
                    retries_remain = attempt < self.max_retries

                    if can_retry and retries_remain:
                        delay = min(
                            self.retry_delay_seconds * (2**attempt),
                            self.max_retry_delay_seconds,
                        )
                        print(
                            f"Gemini {model_name} request failed ({exc}); "
                            f"retrying in {delay:g}s "
                            f"({attempt + 1}/{self.max_retries})."
                        )
                        self.sleep_fn(delay)
                        continue

                    fallback_remains = model_index + 1 < len(self.models)
                    if fallback_remains and self._can_use_fallback(exc):
                        print(
                            f"Switching from Gemini {model_name} "
                            f"to {self.models[model_index + 1]}."
                        )
                        break

                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("Gemini enrichment failed without returning a result.")

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        if isinstance(error, errors.APIError):
            return error.code in {408, 429} or 500 <= error.code <= 599
        return isinstance(
            error,
            (httpx.TransportError, TimeoutError, ConnectionError),
        )

    @classmethod
    def _can_use_fallback(cls, error: Exception) -> bool:
        if cls._is_retryable(error):
            return True
        return isinstance(error, errors.APIError) and error.code == 404

    def enrich_dataframe(
        self,
        events_df: pd.DataFrame,
        source_csv_path: str | Path,
        enriched_output_path: str | Path,
        sleep_seconds: float = 1.0,
        resume: bool = True,
    ) -> pd.DataFrame:
        """Enrich this batch, update source status, and save model outputs separately."""
        source_path = Path(source_csv_path)
        output_path = Path(enriched_output_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source events CSV does not exist: {source_path}")

        source_df = pd.read_csv(source_path)
        if "setlist_id" not in source_df.columns:
            raise ValueError("Source events CSV must contain a 'setlist_id' column.")
        if "enriched" not in source_df.columns:
            source_df["enriched"] = False
        source_df["enriched"] = source_df["enriched"].map(self._as_bool)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        saved_by_id: dict[str, dict[str, Any]] = {}
        if resume and output_path.exists():
            saved_df = pd.read_csv(output_path)
            if "setlist_id" in saved_df.columns and "event_type" in saved_df.columns:
                for record in saved_df.to_dict(orient="records"):
                    setlist_id = record.get("setlist_id")
                    if pd.notna(setlist_id) and pd.notna(record.get("event_type")):
                        saved_by_id[str(setlist_id)] = record

        events_df["enriched"] = events_df.get("enriched", False)
        output_records = []
        rows = list(events_df.to_dict(orient="records"))

        for position, (row_index, row) in enumerate(zip(events_df.index, rows), start=1):
            setlist_id = row.get("setlist_id")
            if pd.isna(setlist_id):
                raise ValueError("Every event in a batch must have a setlist_id.")
            key = str(setlist_id)
            source_matches = source_df["setlist_id"].astype(str) == key
            source_marked = source_df.loc[source_matches, "enriched"].any()

            if source_marked or key in saved_by_id:
                if key in saved_by_id:
                    output_records.append(saved_by_id[key])
                events_df.loc[row_index, "enriched"] = True
                source_df.loc[source_matches, "enriched"] = True
                print(f"[{position}/{len(rows)}] Already enriched: {setlist_id}")
                continue

            enrichment = self.enrich_event(row).model_dump()
            confidence = enrichment.pop("confidence")
            enrichment.update(
                {f"confidence_{name}": value for name, value in confidence.items()}
            )
            record = {
                name: row.get(name)
                for name in (
                    "setlist_id",
                    "event_name",
                    "event_date",
                    "artist_name",
                    "venue_name",
                    "city",
                    "setlist_url",
                )
            }
            record.update(enrichment)

            pd.DataFrame([record]).to_csv(
                output_path,
                mode="a",
                header=not output_path.exists(),
                index=False,
            )
            saved_by_id[key] = record
            output_records.append(record)

            source_df.loc[source_matches, "enriched"] = True
            source_df.to_csv(source_path, index=False)
            events_df.loc[row_index, "enriched"] = True
            print(f"[{position}/{len(rows)}] Enriched: {setlist_id}")

            if sleep_seconds > 0 and position < len(rows):
                time.sleep(sleep_seconds)

        return pd.DataFrame(output_records)

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if pd.isna(value):
            return False
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)