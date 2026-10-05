"""Cross-source deduplication.

Two listings are treated as the same event when they share a URL, or when their
titles are very similar, they start within 30 minutes of each other, and they
are at the same venue (or within a quarter mile). The more complete listing
wins and missing fields are filled from the duplicate.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .geo import haversine_miles
from .models import Event

STOPWORDS = {"the", "a", "an", "and", "of", "at", "in", "for", "with", "to", "on", "&"}
START_TOLERANCE_SECONDS = 30 * 60
TITLE_SIMILARITY = 0.7


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _norm_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip().lower()).rstrip("/").split("?")[0]


def _same_place(a: Event, b: Event) -> bool:
    if a.format == "online" and b.format == "online":
        return True
    if a.venue_name and b.venue_name and _jaccard(_tokens(a.venue_name), _tokens(b.venue_name)) >= 0.5:
        return True
    if None not in (a.lat, a.lon, b.lat, b.lon):
        return haversine_miles(a.lat, a.lon, b.lat, b.lon) <= 0.25
    return False


def is_duplicate(a: Event, b: Event) -> bool:
    if a.uid == b.uid:
        return True
    if a.url and b.url and _norm_url(a.url) == _norm_url(b.url) and a.start == b.start:
        return True
    if abs((a.start - b.start).total_seconds()) > START_TOLERANCE_SECONDS:
        return False
    if _jaccard(_tokens(a.title), _tokens(b.title)) < TITLE_SIMILARITY:
        return False
    return _same_place(a, b)


def _merge(keep: Event, other: Event) -> Event:
    for name in keep.__dataclass_fields__:
        if name in ("quality_score", "issues", "source_id", "source_event_id"):
            continue
        if getattr(keep, name) in (None, "", []) and getattr(other, name) not in (None, "", []):
            setattr(keep, name, getattr(other, name))
    keep.categories = sorted((set(keep.categories) | set(other.categories)) - {"other"}) or ["other"]
    return keep


def deduplicate(events: list[Event]) -> tuple[list[Event], int]:
    """Return (unique events, number of duplicates removed)."""
    # Bucket by start day so we only compare plausible pairs.
    buckets: dict[str, list[Event]] = defaultdict(list)
    for ev in sorted(events, key=lambda e: -e.quality_score):
        buckets[ev.start.date().isoformat()].append(ev)

    unique: list[Event] = []
    removed = 0
    for day_events in buckets.values():
        kept: list[Event] = []
        for ev in day_events:
            match = next((k for k in kept if is_duplicate(k, ev)), None)
            if match:
                _merge(match, ev)
                removed += 1
            else:
                kept.append(ev)
        unique.extend(kept)
    return unique, removed