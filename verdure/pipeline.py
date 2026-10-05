"""One full refresh: ingest -> validate -> dedupe -> store -> rank -> write outputs."""

from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path

from .dedupe import deduplicate
from .geo import AREAS, haversine_miles
from .models import Event, utcnow
from .ranking import Ranked, rank_for_user
from .sources import build_sources
from .store import EventStore, atomic_write_json, read_json
from .users import UserState, interaction_sets, learned_affinity, load_users
from .validate import is_publishable, validate

log = logging.getLogger("verdure.pipeline")


def _nearest_area(ev: Event) -> str:
    if ev.city:
        return ev.city.lower()
    if ev.lat is None or ev.lon is None:
        return "online" if ev.format == "online" else "unknown"
    name, (lat, lon) = min(AREAS.items(), key=lambda kv: haversine_miles(ev.lat, ev.lon, *kv[1]))
    return name if haversine_miles(ev.lat, ev.lon, lat, lon) <= 4 else "other"


def ingest(cfg: dict, base_dir: str, store: EventStore) -> tuple[list[Event], dict]:
    """Fetch every enabled source. A failed source keeps its last good events."""
    events: list[Event] = []
    source_stats: dict[str, dict] = {}
    for src in build_sources(cfg["sources"], base_dir):
        t0 = time.monotonic()
        try:
            fetched = src.fetch()
            events.extend(fetched)
            source_stats[src.id] = {"status": "ok", "fetched": len(fetched),
                                    "seconds": round(time.monotonic() - t0, 2)}
            log.info("%-14s fetched %d events", src.id, len(fetched))
        except Exception as exc:  # one bad feed must never stop the refresh
            kept = [e for e in store.all() if e.source_id == src.id]
            events.extend(kept)
            source_stats[src.id] = {"status": "error", "error": str(exc)[:300], "kept_previous": len(kept)}
            log.error("%-14s FAILED (%s); keeping %d previous events", src.id, exc, len(kept))
    return events, source_stats


def build_index(raw: list[Event], cfg: dict) -> tuple[list[Event], list[Event], int]:
    """Validate and dedupe. Returns (publishable, rejected, duplicates_removed)."""
    for ev in raw:
        validate(ev, cfg["region"], cfg["schedule"])
    good = [e for e in raw if is_publishable(e)]
    rejected = [e for e in raw if not is_publishable(e)]
    unique, removed = deduplicate(good)
    for ev in unique:  # merged listings may have gained fields
        validate(ev, cfg["region"], cfg["schedule"])
    return unique, rejected, removed


def _feed_entry(rank: int, r: Ranked) -> dict:
    ev = r.event
    return {
        "rank": rank,
        "uid": ev.uid,
        "title": ev.title,
        "start": ev.start.isoformat(),
        "end": ev.end.isoformat() if ev.end else None,
        "venue": ev.venue_name,
        "address": ev.address,
        "distance_miles": r.distance_miles,
        "categories": ev.categories,
        "is_free": ev.is_free,
        "price_min": ev.price_min,
        "organizer": ev.organizer,
        "url": ev.url,
        "image_url": ev.image_url,
        "format": ev.format,
        "status": ev.status,
        "score": r.final,
        "components": r.components,
        "diversity_penalty": round(r.diversity_penalty, 3),
        "reasons": r.reasons,
        "saved": r.engaged,
        "notify": r.notify,
    }


def rank_all(events: list[Event], cfg: dict, base_dir: str) -> dict:
    paths = cfg["paths"]
    out_dir = Path(base_dir) / paths["output_dir"]
    users = load_users(str(Path(base_dir) / paths["users_dir"]))
    by_uid = {e.uid: e for e in events}
    live = set(by_uid)
    rcfg = cfg["ranking"]
    summary = {"users": len(users), "notifications": 0, "empty_feeds": 0}

    for user in users:
        state = UserState(str(out_dir), user.user_id)
        state.prune(live)
        affinity = learned_affinity(user, by_uid, rcfg.get("learning_rate", 0.08),
                                    rcfg.get("learned_affinity_cap", 1.0))
        excluded, engaged = interaction_sets(user)
        ranked = rank_for_user(events, user, state, affinity, excluded, engaged, cfg)

        new_notes = []
        for r in ranked:
            if r.notify:
                state.mark_notified(r.event.uid)
                new_notes.append({
                    "uid": r.event.uid, "title": r.event.title, "start": r.event.start.isoformat(),
                    "message": f"{r.event.title} — {', '.join(r.reasons[:2])}".rstrip(" —, "),
                    "created_at": utcnow().isoformat(),
                })
        state.mark_shown([r.event.uid for r in ranked])
        state.save()

        atomic_write_json(out_dir / "feeds" / f"{user.user_id}.json", {
            "user_id": user.user_id,
            "generated_at": utcnow().isoformat(),
            "count": len(ranked),
            "learned_affinity": {k: round(v, 3) for k, v in sorted(affinity.items())},
            "events": [_feed_entry(i + 1, r) for i, r in enumerate(ranked)],
        })

        if new_notes:
            # Pending queue: whatever sends push notifications reads and clears this file.
            q_path = out_dir / "notifications" / f"{user.user_id}.json"
            queue = read_json(q_path, [])
            atomic_write_json(q_path, queue + new_notes)
            summary["notifications"] += len(new_notes)
        if not ranked:
            summary["empty_feeds"] += 1
    return summary


def write_report(cfg: dict, base_dir: str, publishable: list[Event], rejected: list[Event],
                 duplicates: int, source_stats: dict, rank_summary: dict, store_changes: dict) -> dict:
    out_dir = Path(base_dir) / cfg["paths"]["output_dir"]
    n = len(publishable)
    complete = sum(1 for e in publishable if e.quality_score >= 0.85)
    issue_counts = Counter(i for e in publishable for i in e.issues)
    reject_counts = Counter(i for e in rejected for i in e.issues)
    report = {
        "generated_at": utcnow().isoformat(),
        "region": cfg["region"]["name"],
        "sources": source_stats,
        "listings": {
            "publishable": n,
            "rejected": len(rejected),
            "duplicates_removed": duplicates,
            "added_this_run": store_changes.get("added", 0),
            "removed_this_run": store_changes.get("removed", 0),
            "complete_pct": round(100 * complete / n, 1) if n else 0.0,
            "avg_quality": round(sum(e.quality_score for e in publishable) / n, 3) if n else 0.0,
        },
        "common_issues": dict(issue_counts.most_common(10)),
        "rejection_reasons": dict(reject_counts.most_common()),
        "coverage_by_area": dict(Counter(_nearest_area(e) for e in publishable).most_common()),
        "coverage_by_category": dict(Counter(c for e in publishable for c in e.categories).most_common()),
        "users": rank_summary,
    }
    atomic_write_json(out_dir / "report.json", report)
    atomic_write_json(out_dir / "rejected.json", [
        {"uid": e.uid, "source": e.source_id, "title": e.title,
         "start": e.start.isoformat() if e.start else None, "issues": e.issues, "url": e.url}
        for e in rejected if "already_ended" not in e.issues
    ])
    return report


def refresh(cfg: dict, base_dir: str) -> dict:
    """Full refresh cycle. Safe to call repeatedly."""
    store = EventStore(str(Path(base_dir) / cfg["paths"]["store"]))
    raw, source_stats = ingest(cfg, base_dir, store)
    publishable, rejected, dupes = build_index(raw, cfg)
    changes = store.upsert_many(publishable)
    changes["removed"] = store.prune({e.uid for e in publishable})
    store.save()
    rank_summary = rank_all(publishable, cfg, base_dir)
    report = write_report(cfg, base_dir, publishable, rejected, dupes, source_stats, rank_summary, changes)
    log.info("Refresh done: %d live events (+%d / -%d), %d rejected, %d dupes, %d users, %d notifications",
             len(publishable), changes["added"], changes["removed"], len(rejected), dupes,
             rank_summary["users"], rank_summary["notifications"])
    return report


def rerank_only(cfg: dict, base_dir: str) -> dict:
    """Rebuild user feeds from the stored index without re-fetching sources."""
    store = EventStore(str(Path(base_dir) / cfg["paths"]["store"]))
    events = [validate(e, cfg["region"], cfg["schedule"]) for e in store.all()]
    events = [e for e in events if is_publishable(e)]
    summary = rank_all(events, cfg, base_dir)
    log.info("Re-ranked %d users after profile changes (%d notifications)",
             summary["users"], summary["notifications"])
    return summary