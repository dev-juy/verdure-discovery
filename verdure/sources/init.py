"""Source adapter registry. Map config.yaml `type` values to adapter classes."""

from .base import Source
from .ical import ICalSource
from .livewhale import LiveWhaleSource
from .submissions import SubmissionsSource
from .ticketmaster import TicketmasterSource

REGISTRY: dict[str, type[Source]] = {
    "ical": ICalSource,
    "livewhale": LiveWhaleSource,
    "ticketmaster": TicketmasterSource,
    "submissions": SubmissionsSource,
}


def build_sources(source_cfgs: list[dict], base_dir: str) -> list[Source]:
    sources = []
    for cfg in source_cfgs:
        if not cfg.get("enabled", True):
            continue
        cls = REGISTRY.get(cfg.get("type"))
        if cls is None:
            raise ValueError(f"Unknown source type '{cfg.get('type')}' for source '{cfg.get('id')}'")
        sources.append(cls(cfg, base_dir=base_dir))
    return sources