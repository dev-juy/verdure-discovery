"""User profiles, feedback learning, and per-user engine state.

Profiles live in data/users/<user_id>.json and are written by the app (or by
hand). The engine never edits them. Its own memory of what each user has been
shown and notified about lives in output/state/<user_id>.json.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dateutil import parser as dtparser

from .models import Event, to_utc, utcnow
from .store import atomic_write_json, read_json

log = logging.getLogger("verdure.users")

# How strongly each action signals interest. Negative = not interested.
ACTION_WEIGHTS = {
    "rsvp": 1.0,
    "register_click": 0.9,
    "save": 0.8,
    "share": 0.7,
    "click": 0.3,
    "dismiss": -0.6,
    "hide": -1.0,
    "report": 0.0,   # reports flag the listing, not the user's taste
}
# Events the user explicitly removed are never shown again.
EXCLUDING_ACTIONS = {"dismiss", "hide", "report"}
ENGAGED_ACTIONS = {"rsvp", "register_click", "save"}
FEEDBACK_HALF_LIFE_DAYS = 30


@dataclass
class UserProfile:
    user_id: str
    area: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    max_distance_miles: float = 10.0
    interests: list[str] = field(default_factory=list)
    date_range_days: int = 14
    max_price: Optional[float] = None
    formats: list[str] = field(default_factory=lambda: ["in_person", "hybrid"])
    child_ages: list[int] = field(default_factory=list)
    indoor_only: bool = False
    interactions: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "UserProfile":
        data = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        data["interests"] = [i.lower() for i in data.get("interests", [])]
        return cls(**data)


def load_users(users_dir: str) -> list[UserProfile]:
    users = []
    for path in sorted(Path(users_dir).glob("*.json")):
        raw = read_json(path, None)
        if not raw or "user_id" not in raw:
            log.warning("Skipping user file without user_id: %s", path.name)
            continue
        try:
            users.append(UserProfile.from_dict(raw))
        except TypeError as exc:
            log.warning("Skipping malformed user file %s: %s", path.name, exc)
    return users


def users_fingerprint(users_dir: str) -> tuple:
    """Changes whenever any profile is added, edited, or removed."""
    return tuple(sorted((p.name, p.stat().st_mtime) for p in Path(users_dir).glob("*.json")))


def learned_affinity(user: UserProfile, events_by_uid: dict[str, Event],
                     learning_rate: float, cap: float) -> dict[str, float]:
    """Per-category affinity in [-cap, cap] learned from recent feedback.

    Recent actions count more (30-day half-life), and the learning rate keeps
    any one burst of clicks from overriding the user's stated interests.
    """
    now = utcnow()
    totals: dict[str, float] = {}
    for it in user.interactions:
        weight = ACTION_WEIGHTS.get(it.get("action", ""), 0.0)
        if weight == 0.0:
            continue
        cats = it.get("categories")
        if not cats:
            ev = events_by_uid.get(it.get("uid", ""))
            cats = ev.categories if ev else []
        if not cats:
            continue
        decay = 1.0
        if it.get("at"):
            try:
                age_days = (now - to_utc(dtparser.parse(it["at"]))).total_seconds() / 86400
                decay = 0.5 ** (max(age_days, 0) / FEEDBACK_HALF_LIFE_DAYS)
            except (ValueError, TypeError):
                pass
        for c in cats:
            totals[c] = totals.get(c, 0.0) + weight * decay
    return {c: max(-cap, min(cap, math.tanh(v * learning_rate * 5) * cap)) for c, v in totals.items()}


def interaction_sets(user: UserProfile) -> tuple[set[str], set[str]]:
    excluded = {it["uid"] for it in user.interactions if it.get("action") in EXCLUDING_ACTIONS and it.get("uid")}
    engaged = {it["uid"] for it in user.interactions if it.get("action") in ENGAGED_ACTIONS and it.get("uid")}
    return excluded, engaged


class UserState:
    """What the engine has already shown and notified for one user."""

    def __init__(self, output_dir: str, user_id: str):
        self.path = Path(output_dir) / "state" / f"{user_id}.json"
        raw = read_json(self.path, {})
        self.first_shown: dict[str, str] = raw.get("first_shown", {})
        self.notified: dict[str, str] = raw.get("notified", {})

    def days_since_first_shown(self, uid: str) -> Optional[float]:
        ts = self.first_shown.get(uid)
        if not ts:
            return None
        return (utcnow() - dtparser.isoparse(ts)).total_seconds() / 86400

    def mark_shown(self, uids: list[str]) -> None:
        now = utcnow().isoformat()
        for uid in uids:
            self.first_shown.setdefault(uid, now)

    def mark_notified(self, uid: str) -> None:
        self.notified[uid] = utcnow().isoformat()

    def prune(self, live_uids: set[str]) -> None:
        self.first_shown = {k: v for k, v in self.first_shown.items() if k in live_uids}
        self.notified = {k: v for k, v in self.notified.items() if k in live_uids}

    def save(self) -> None:
        atomic_write_json(self.path, {"first_shown": self.first_shown, "notified": self.notified})