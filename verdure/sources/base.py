"""Base class every source adapter extends."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from ..models import Event

log = logging.getLogger("verdure.sources")

USER_AGENT = "VerdureEventIngest/0.1 (+https://verdure.app)"


class Source(ABC):
    """An adapter turns one external feed into a list of standard Events.

    To add a new source type: subclass Source, implement fetch(), and register
    the class in sources/__init__.py under a type name used in config.yaml.
    """

    def __init__(self, cfg: dict, base_dir: str = "."):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg.get("name", self.id)
        self.base_dir = base_dir

    @abstractmethod
    def fetch(self) -> list[Event]:
        ...

    def http_get(self, url: str, params: dict | None = None, timeout: int = 30) -> requests.Response:
        resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp