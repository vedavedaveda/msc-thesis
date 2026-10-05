import os
import time
from typing import Any

import requests


class SetlistFMEventSource:
    """Fetch and paginate Setlist.fm search results for music events."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.setlist.fm/rest/1.0",
        sleep_seconds: float = 1.0,
    ) -> None:
        self.api_key = api_key or os.getenv("SETLISTFM_API_KEY")
        if not self.api_key:
            raise ValueError("Missing SETLISTFM_API_KEY. Pass api_key or set the environment variable.")

        self.base_url = base_url
        self.sleep_seconds = sleep_seconds
        self.headers = {
            "Accept": "application/json",
            "x-api-key": self.api_key,
        }

    def fetch_events(
        self,
        country_code: str,
        state: str | None = None,
        city_name: str | None = None,
        year: int | None = None,
        per_page: int = 20,
        max_pages: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Fetch all available Setlist.fm search results across pages.

        Returns a payload shaped as {"setlist": [...]}, matching the
        structure returned by the original Setlist.fm search endpoint.
        """
        all_setlists: list[dict[str, Any]] = []
        page = 1

        while True:
            if max_pages is not None and page > max_pages:
                break

            params: dict[str, Any] = {
                "countryCode": country_code,
                "p": page,
                "page": page,
                "per_page": per_page,
            }

            if state is not None:
                params["state"] = state
            if city_name is not None:
                params["cityName"] = city_name
            if year is not None:
                params["year"] = year

            response = requests.get(
                f"{self.base_url}/search/setlists",
                headers=self.headers,
                params=params,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Setlist.fm request failed on page {page}: "
                    f"HTTP {response.status_code}"
                )

            payload = response.json()
            page_setlists = payload.get("setlist", [])
            if not page_setlists:
                break

            all_setlists.extend(page_setlists)

            if len(page_setlists) < per_page:
                break

            if max_pages is not None and page >= max_pages:
                break

            page += 1
            if self.sleep_seconds > 0:
                time.sleep(self.sleep_seconds)

        return {"setlist": all_setlists}


def fetch_setlistfm_events(
    country_code: str,
    state: str | None = None,
    city_name: str | None = None,
    year: int | None = None,
    per_page: int = 20,
    max_pages: int | None = None,
    api_key: str | None = None,
    sleep_seconds: float = 1.0,
) -> dict[str, list[dict[str, Any]]]:
    """Convenience wrapper around the SetlistFMEventSource class."""
    source = SetlistFMEventSource(api_key=api_key, sleep_seconds=sleep_seconds)
    return source.fetch_events(
        country_code=country_code,
        state=state,
        city_name=city_name,
        year=year,
        per_page=per_page,
        max_pages=max_pages,
    )
