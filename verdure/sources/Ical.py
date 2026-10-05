"""iCalendar (.ics) adapter.

Works for any platform that publishes a public iCal feed: Localist (SJSU),
CivicPlus calendars, many library and parks calendars, Google Calendar exports.
"""

from __future__ import annotations

from datetime import date, datetime, time

from icalendar import Calendar

from ..models import Event, clean_text, infer_categories, to_utc
from .base import Source


def _to_dt(value) -> datetime | None:
    if value is None:
        return None
    v = value.dt if hasattr(value, "dt") else value
    if isinstance(v, datetime):
        return to_utc(v)
    if isinstance(v, date):
        # All-day event: anchor to 9am local so it sorts sensibly.
        return to_utc(datetime.combine(v, time(9, 0)))
    return None


def _text(component, key: str) -> str:
    val = component.get(key)
    if val is None:
        return ""
    if isinstance(val, list):
        val = val[0]
    return clean_text(str(val))


def _categories(component) -> list[str]:
    raw = component.get("CATEGORIES")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for item in items:
        cats = getattr(item, "cats", None)
        if cats:
            out.extend(str(c) for c in cats)
        else:
            out.extend(s.strip() for s in str(item).split(","))
    return [c.lower() for c in out if c]


def parse_ics(text: str | bytes, source_id: str, default_category: str | None = None,
              organizer_fallback: str = "") -> list[Event]:
    cal = Calendar.from_ical(text)
    events: list[Event] = []
    for comp in cal.walk("VEVENT"):
        start = _to_dt(comp.get("DTSTART"))
        if start is None:
            continue
        uid = _text(comp, "UID") or f"{_text(comp, 'SUMMARY')}-{start.isoformat()}"
        title = _text(comp, "SUMMARY")
        description = _text(comp, "DESCRIPTION")
        location = _text(comp, "LOCATION")

        lat = lon = None
        geo = comp.get("GEO")
        if geo is not None:
            try:
                lat, lon = float(geo.latitude), float(geo.longitude)
            except (AttributeError, ValueError):
                pass

        raw_cats = _categories(comp)
        cats = infer_categories(title, f"{description} {' '.join(raw_cats)}", default_category)

        status = _text(comp, "STATUS").lower()
        organizer = organizer_fallback
        org = comp.get("ORGANIZER")
        if org is not None:
            organizer = clean_text(org.params.get("CN", "")) or organizer_fallback

        events.append(Event(
            source_id=source_id,
            source_event_id=f"{uid}@{start.isoformat()}",
            title=title,
            start=start,
            end=_to_dt(comp.get("DTEND")),
            description=description,
            venue_name=location.split(",")[0].strip() if location else "",
            address=location,
            lat=lat,
            lon=lon,
            categories=cats,
            organizer=organizer,
            url=_text(comp, "URL"),
            format="online" if any(w in location.lower() for w in ("zoom", "online", "virtual")) else "in_person",
            status="cancelled" if status == "cancelled" else "scheduled",
        ))
    return events


class ICalSource(Source):
    def fetch(self) -> list[Event]:
        # "path" reads a local .ics file (handy for testing or manual exports); "url" fetches a feed.
        if self.cfg.get("path"):
            from pathlib import Path
            content = (Path(self.base_dir) / self.cfg["path"]).read_bytes()
        else:
            content = self.http_get(self.cfg["url"]).content
        return parse_ics(
            content,
            source_id=self.id,
            default_category=self.cfg.get("default_category"),
            organizer_fallback=self.name,
        )