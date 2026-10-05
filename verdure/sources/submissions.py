"""Organizer submissions adapter.

Organizers' events land as JSON files in data/submissions/ (one event per file,
or a list of events). Whatever form or backend collects them just needs to drop
files here. Editing or deleting a file updates or removes the listing on the
next refresh, which gives organizers a correction and cancellation path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from dateutil import parser as dtparser

from ..models import Event, clean_text, infer_categories, to_utc
from .base import Source

log = logging.getLogger("verdure.sources.submissions")


def parse_submission(d: dict, source_id: str, file_stem: str) -> Event:
    title = clean_text(d.get("title"))
    desc = clean_text(d.get("description"))
    cats = [c.lower() for c in d.get("categories", []) if c]
    price = d.get("price")
    is_free = d.get("is_free")
    if is_free is None and price is not None:
        is_free = float(price) == 0

    return Event(
        source_id=source_id,
        source_event_id=str(d.get("id") or file_stem),
        title=title,
        start=to_utc(dtparser.parse(d["start"])),
        end=to_utc(dtparser.parse(d["end"])) if d.get("end") else None,
        description=desc,
        venue_name=clean_text(d.get("venue_name")),
        address=clean_text(d.get("address")),
        city=clean_text(d.get("city")),
        lat=d.get("lat"),
        lon=d.get("lon"),
        categories=cats or infer_categories(title, desc),
        price_min=float(price) if price is not None else (0.0 if is_free else None),
        price_max=float(d["price_max"]) if d.get("price_max") is not None else None,
        is_free=is_free,
        organizer=clean_text(d.get("organizer")),
        organizer_contact=clean_text(d.get("organizer_contact")),
        url=d.get("url", ""),
        format=d.get("format", "in_person"),
        age_min=d.get("age_min"),
        age_max=d.get("age_max"),
        indoor=d.get("indoor"),
        accessibility=clean_text(d.get("accessibility")),
        capacity=d.get("capacity"),
        status=d.get("status", "scheduled"),
        image_url=d.get("image_url", ""),
    )


class SubmissionsSource(Source):
    def fetch(self) -> list[Event]:
        folder = Path(self.base_dir) / self.cfg.get("folder", "data/submissions")
        events: list[Event] = []
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else [data]
                for i, item in enumerate(items):
                    stem = path.stem if len(items) == 1 else f"{path.stem}-{i}"
                    events.append(parse_submission(item, self.id, stem))
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                log.warning("Skipping bad submission %s: %s", path.name, exc)
        return events