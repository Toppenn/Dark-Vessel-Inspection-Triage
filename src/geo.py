"""Minimal geospatial helpers, no external dependencies.

When we move to real polygons (Natura 2000 marine, WDPA) this should be
replaced by shapely + geopandas. For the prototype, ray casting is enough
and keeps the project installable in ten seconds.
"""

import math


def point_in_polygon(lat: float, lon: float, polygon: list) -> bool:
    """Ray casting. Polygon is a list of [lat, lon] pairs."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        if (lon_i > lon) != (lon_j > lon):
            crossing = (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i) + lat_i
            if lat < crossing:
                inside = not inside
        j = i
    return inside


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in kilometres."""
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return round(2 * radius * math.asin(math.sqrt(a)), 2)


def centroid(polygon: list) -> tuple:
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    return (sum(lats) / len(lats), sum(lons) / len(lons))
