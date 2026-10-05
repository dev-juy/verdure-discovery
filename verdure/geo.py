"""Distance helpers and known neighborhood centers."""

from __future__ import annotations

import math
from typing import Optional

# Approximate centers for areas users can pick instead of exact coordinates.
AREAS = {
    "downtown san jose": (37.3352, -121.8811),
    "sjsu": (37.3352, -121.8811),
    "willow glen": (37.3030, -121.8990),
    "almaden": (37.2200, -121.8640),
    "cambrian": (37.2560, -121.9300),
    "evergreen": (37.3100, -121.7700),
    "santa clara": (37.3541, -121.9552),
    "sunnyvale": (37.3688, -122.0363),
    "campbell": (37.2872, -121.9500),
    "milpitas": (37.4323, -121.8996),
}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def resolve_point(area: Optional[str], lat: Optional[float], lon: Optional[float]):
    """Return (lat, lon) from explicit coordinates or a named area."""
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    if area and area.lower() in AREAS:
        return AREAS[area.lower()]
    return None