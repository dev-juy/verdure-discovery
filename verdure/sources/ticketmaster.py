"""Ticketmaster Discovery API adapter.

Free tier: 5,000 calls/day. The API key is read from an environment variable
named in config.yaml (default TICKETMASTER_API_KEY) so it never lives in code.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from dateutil import parser as dtparser

from ..models import Event, clean_text, infer_categories, to_utc, utcnow
from .base import Source

log = logging.getLogger("verdure.sources.ticketmaster")

API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 200
MAX_PAGES = 5  # 1,000 events per refresh is plenty and stays far under the daily cap

SEGMENT_MAP = {
    "music": "music",
    "sports": "sports",
    "arts & theatre": "theater",
    "film": "film",
    "family": "family",
    "miscellaneous": "other",
}


def parse_ticketmaster(payload: dict, source_id: str) -> list[Event]:
    items = (payload.get("_embedded") or {}).get("events", [])
    events: list[Event] = []
    for item in items:
        dates = item.get("dates", {})
        start_info = dates.get("start", {})
        start_raw = start_info.get("dateTime") or start_info.get("localDate")
        if not start_raw:
            continue
        start = to_utc(dtparser.parse(start_raw))

        venue = ((item.get("_embedded") or {}).get("venues") or [{}])[0]
        loc = venue.get("location") or {}
        address_parts = [
            (venue.get("address") or {}).get("line1", ""),
            (venue.get("city") or {}).get("name", ""),
            (venue.get("state") or {}).get("stateCode", ""),
        ]

        cats: list[str] = []
        for c in item.get("classifications", []) or []:
            seg = ((c.get("segment") or {}).get("name") or "").lower()
            if seg in SEGMENT_MAP:
                cats.append(SEGMENT_MAP[seg])
            if (c.get("family")) is True:
                cats.append("family")
        title = clean_text(item.get("name"))
        desc = clean_text(item.get("info") or item.get("pleaseNote") or "")
        if not cats or cats == ["other"]:
            cats = infer_categories(title, desc)

        prices = item.get("priceRanges") or []
        pmin = min((p.get("min") for p in prices if p.get("min") is not None), default=None)
        pmax = max((p.get("max") for p in prices if p.get("max") is not None), default=None)

        status_code = ((dates.get("status") or {}).get("code") or "").lower()
        images = item.get("images") or []

        events.append(Event(
            source_id=source_id,
            source_event_id=item.get("id", ""),
            title=title,
            start=start,
            description=desc,
            venue_name=clean_text(venue.get("name")),
            address=", ".join(p for p in address_parts if p),
            city=(venue.get("city") or {}).get("name", ""),
            lat=float(loc["latitude"]) if loc.get("latitude") else None,
            lon=float(loc["longitude"]) if loc.get("longitude") else None,
            categories=sorted(set(cats)),
            price_min=pmin,
            price_max=pmax,
            is_free=(pmin == 0) if pmin is not None else None,
            organizer=clean_text((item.get("promoter") or {}).get("name") or venue.get("name") or ""),
            url=item.get("url", ""),
            status="cancelled" if status_code == "cancelled" else
                   "postponed" if status_code in ("postponed", "rescheduled") else "scheduled",
            image_url=images[0].get("url", "") if images else "",
        ))
    return events


class TicketmasterSource(Source):
    def fetch(self) -> list[Event]:
        key = os.environ.get(self.cfg.get("api_key_env", "TICKETMASTER_API_KEY"))
        if not key:
            log.warning("Ticketmaster skipped: set the %s environment variable",
                        self.cfg.get("api_key_env", "TICKETMASTER_API_KEY"))
            return []

        now = utcnow()
        params = {
            "apikey": key,
            "latlong": f"{self.cfg['lat']},{self.cfg['lon']}",
            "radius": self.cfg.get("radius_miles", 25),
            "unit": "miles",
            "size": PAGE_SIZE,
            "sort": "date,asc",
            "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": (now + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        events: list[Event] = []
        for page in range(MAX_PAGES):
            params["page"] = page
            payload = self.http_get(API_URL, params=params).json()
            events.extend(parse_ticketmaster(payload, self.id))
            total_pages = (payload.get("page") or {}).get("totalPages", 1)
            if page + 1 >= total_pages:
                break
        return events