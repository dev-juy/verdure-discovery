"""Listing validation rules and completeness scoring.

Every event gets a quality_score (0-1) and a list of issues. Events with a
blocking issue are rejected; the rest are kept but ranked lower when incomplete.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlparse

from .geo import haversine_miles
from .models import VALID_FORMATS, Event, utcnow

# Essential fields and how much each contributes to quality_score.
ESSENTIAL_WEIGHTS = {
    "title": 0.15,
    "description": 0.15,
    "start": 0.15,
    "end": 0.05,
    "location": 0.15,
    "category": 0.05,
    "price": 0.10,
    "organizer": 0.05,
    "url": 0.15,
}

BLOCKING = {
    "missing_title",
    "missing_start",
    "end_before_start",
    "already_ended",
    "cancelled",
    "outside_region",
    "missing_location_in_person",
}


def _valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def validate(event: Event, region_cfg: dict, schedule_cfg: dict) -> Event:
    issues: list[str] = []
    score = 0.0
    now = utcnow()

    if event.title and len(event.title) >= 3:
        score += ESSENTIAL_WEIGHTS["title"]
    else:
        issues.append("missing_title")

    if len(event.description) >= 40:
        score += ESSENTIAL_WEIGHTS["description"]
    elif event.description:
        score += ESSENTIAL_WEIGHTS["description"] / 2
        issues.append("short_description")
    else:
        issues.append("missing_description")

    if event.start:
        score += ESSENTIAL_WEIGHTS["start"]
    else:
        issues.append("missing_start")

    if event.end:
        score += ESSENTIAL_WEIGHTS["end"]
        if event.start and event.end < event.start:
            issues.append("end_before_start")
    else:
        issues.append("missing_end")

    end_or_start = event.end or event.start
    grace = timedelta(hours=schedule_cfg.get("drop_past_after_hours", 2))
    if end_or_start and end_or_start + grace < now:
        issues.append("already_ended")

    if event.format not in VALID_FORMATS:
        event.format = "in_person"

    has_location = bool(event.venue_name or event.address) or (
        event.lat is not None and event.lon is not None
    )
    if event.format == "online":
        score += ESSENTIAL_WEIGHTS["location"]
    elif has_location:
        score += ESSENTIAL_WEIGHTS["location"]
    else:
        issues.append("missing_location_in_person")

    if event.lat is not None and event.lon is not None and event.format != "online":
        center = region_cfg["center"]
        dist = haversine_miles(center["lat"], center["lon"], event.lat, event.lon)
        if dist > region_cfg.get("max_radius_miles", 30):
            issues.append("outside_region")
    elif event.format != "online":
        issues.append("not_geocoded")

    if event.categories and event.categories != ["other"]:
        score += ESSENTIAL_WEIGHTS["category"]
    else:
        issues.append("missing_category")

    if event.is_free is not None or event.price_min is not None:
        score += ESSENTIAL_WEIGHTS["price"]
    else:
        issues.append("missing_price")

    if event.organizer:
        score += ESSENTIAL_WEIGHTS["organizer"]
    else:
        issues.append("missing_organizer")

    if event.url and _valid_url(event.url):
        score += ESSENTIAL_WEIGHTS["url"]
    elif event.url:
        issues.append("invalid_url")
    else:
        issues.append("missing_url")

    if event.status == "cancelled":
        issues.append("cancelled")

    event.quality_score = round(min(score, 1.0), 3)
    event.issues = issues
    return event


def is_publishable(event: Event) -> bool:
    return not any(issue in BLOCKING for issue in event.issues)