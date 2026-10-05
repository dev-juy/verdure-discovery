"""JSON-file event store with first-seen / last-seen tracking.

A plain JSON file keeps the engine dependency-free. Swap this module for a
database later without touching the rest of the pipeline.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import Event, utcnow


def atomic_write_json(path: str | Path, data) -> None:
    """Write JSON so readers never see a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def read_json(path: str | Path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


class EventStore:
    def __init__(self, path: str):
        self.path = Path(path)
        raw = read_json(self.path, {"events": []})
        self.events: dict[str, Event] = {}
        for d in raw.get("events", []):
            try:
                ev = Event.from_dict(d)
                self.events[ev.uid] = ev
            except (TypeError, ValueError):
                continue

    def upsert_many(self, incoming: list[Event]) -> dict:
        """Add new events, update existing ones. Returns counts."""
        now = utcnow()
        added = updated = 0
        for ev in incoming:
            existing = self.events.get(ev.uid)
            if existing:
                ev.first_seen = existing.first_seen or now
                updated += 1
            else:
                ev.first_seen = now
                added += 1
            ev.last_seen = now
            self.events[ev.uid] = ev
        return {"added": added, "updated": updated}

    def prune(self, keep_uids: set[str]) -> int:
        """Drop events no longer present or no longer publishable."""
        stale = [uid for uid in self.events if uid not in keep_uids]
        for uid in stale:
            del self.events[uid]
        return len(stale)

    def all(self) -> list[Event]:
        return list(self.events.values())

    def save(self) -> None:
        atomic_write_json(
            self.path,
            {
                "updated_at": utcnow().isoformat(),
                "count": len(self.events),
                "events": [e.to_dict() for e in sorted(self.events.values(), key=lambda e: e.start)],
            },
        )