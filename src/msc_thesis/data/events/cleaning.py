from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


class SetlistFMEventCleaner:
    """Normalize Setlist.fm raw search payloads into a tidy event dataframe."""

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else None

    def clean(self, payload: dict[str, Any]) -> pd.DataFrame:
        """Return a pandas DataFrame built from a Setlist.fm payload."""
        events = []

        for setlist in payload.get("setlist", []):
            artist = setlist.get("artist", {})
            venue = setlist.get("venue", {})
            city = venue.get("city", {})
            coordinates = city.get("coords", {})
            country = city.get("country", {})
            tour = setlist.get("tour", {})

            artist_name = artist.get("name")
            venue_name = venue.get("name")

            event = {
                "event_name": f"{artist_name} @ {venue_name}",
                "event_date": setlist.get("eventDate"),
                "start_time": None,
                "end_time": None,
                "artist_name": artist_name,
                "artist_mbid": artist.get("mbid"),
                "artist_url": artist.get("url"),
                "tour_name": tour.get("name"),
                "venue_name": venue_name,
                "venue_id": venue.get("id"),
                "venue_url": venue.get("url"),
                "city": city.get("name"),
                "country": country.get("name"),
                "country_code": country.get("code"),
                "latitude": coordinates.get("lat"),
                "longitude": coordinates.get("long"),
                "notes": setlist.get("info"),
                "setlist_id": setlist.get("id"),
                "setlist_url": setlist.get("url"),
                "last_updated": setlist.get("lastUpdated"),
                "enriched": False,
            }
            events.append(event)

        return pd.DataFrame(events)

    def save(self, events_df: pd.DataFrame, output_path: str | Path) -> Path:
        """Persist the dataframe to disk and return the written path."""
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        events_to_save = events_df.copy()
        if destination.exists() and "setlist_id" in events_to_save.columns:
            existing = pd.read_csv(destination)
            if "setlist_id" in existing.columns and "enriched" in existing.columns:
                enriched_by_id = dict(
                    zip(existing["setlist_id"].astype(str), existing["enriched"])
                )
                current_flags = events_to_save.get("enriched", False)
                events_to_save["enriched"] = [
                    bool(current) or bool(enriched_by_id.get(str(setlist_id), False))
                    for setlist_id, current in zip(
                        events_to_save["setlist_id"], current_flags
                    )
                ]
        events_to_save.to_csv(destination, index=False)
        return destination


def events_from_setlists(payload: dict[str, Any]) -> pd.DataFrame:
    """Convenience function for turning a Setlist.fm payload into an event dataframe."""
    cleaner = SetlistFMEventCleaner()
    return cleaner.clean(payload)


def save_events_dataframe(events_df: pd.DataFrame, output_path: str | Path) -> Path:
    """Persist an events dataframe to disk through the shared cleaner utility."""
    cleaner = SetlistFMEventCleaner()
    return cleaner.save(events_df, output_path)
