"""Standard event data format shared by every source adapter."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

VALID_FORMATS = {"in_person", "online", "hybrid"}

# Canonical categories. Adapters map raw source categories onto these.
CATEGORIES = {
    "family", "kids", "music", "arts", "education", "outdoors", "volunteer",
    "sports", "fitness", "food", "community", "campus", "tech", "social",
    "film", "theater", "workshop", "civic", "other",
}

# Keyword hints used when a source gives no usable category.
CATEGORY_KEYWORDS = {
    "kids": ["storytime", "story time", "toddler", "preschool", "children", "kids", "baby"],
    "family": ["family", "all ages", "parents"],
    "music": ["concert", "music", "band", "live music", "jazz", "orchestra", "dj"],
    "arts": ["art", "gallery", "exhibit", "painting", "craft"],
    "outdoors": ["hike", "walk", "preserve", "trail", "nature", "naturalist", "birding", "park"],
    "volunteer": ["volunteer", "cleanup", "clean-up", "restoration"],
    "education": ["lecture", "talk", "class", "seminar", "tutoring", "lesson"],
    "workshop": ["workshop", "hands-on"],
    "sports": ["game", "match", "tournament", "basketball", "soccer", "baseball"],
    "fitness": ["yoga", "run", "fitness", "workout", "climbing"],
    "food": ["farmers market", "food", "tasting", "cooking"],
    "tech": ["hackathon", "coding", "tech", "robotics", "ai "],
    "film": ["film", "movie", "screening"],
    "theater": ["theater", "theatre", "play", "musical"],
    "civic": ["city council", "town hall", "public meeting", "civic"],
    "social": ["meetup", "mixer", "social", "networking"],
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive datetimes as Pacific local time, the launch market's zone.
        from zoneinfo import ZoneInfo
        dt = dt.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    return dt.astimezone(timezone.utc)


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))  # strip HTML tags
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def infer_categories(title: str, description: str, default: Optional[str] = None) -> list[str]:
    text = f" {title} {description} ".lower()
    found = [cat for cat, words in CATEGORY_KEYWORDS.items() if any(w in text for w in words)]
    if not found and default:
        found = [default]
    return found or ["other"]


@dataclass
class Event:
    source_id: str
    source_event_id: str
    title: str
    start: datetime
    end: Optional[datetime] = None
    description: str = ""
    venue_name: str = ""
    address: str = ""
    city: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    categories: list[str] = field(default_factory=list)
    price_min: Optional[float] = None   # 0.0 means explicitly free
    price_max: Optional[float] = None
    is_free: Optional[bool] = None
    organizer: str = ""
    organizer_contact: str = ""
    url: str = ""
    format: str = "in_person"           # in_person | online | hybrid
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    indoor: Optional[bool] = None
    accessibility: str = ""
    capacity: Optional[int] = None
    status: str = "scheduled"           # scheduled | cancelled | postponed
    image_url: str = ""
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    # Filled in by validation
    quality_score: float = 0.0
    issues: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Stable id for this exact listing from this source."""
        raw = f"{self.source_id}::{self.source_event_id}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("start", "end", "first_seen", "last_seen"):
            if d[key] is not None:
                d[key] = d[key].isoformat()
        d["uid"] = self.uid
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        from dateutil import parser as dtparser

        data = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        for key in ("start", "end", "first_seen", "last_seen"):
            if data.get(key):
                data[key] = to_utc(dtparser.isoparse(data[key]))
        return cls(**data)