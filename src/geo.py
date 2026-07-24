"""Minimal geospatial helpers.

Two polygon representations are accepted, and the demo never needs a dependency:

- The prototype form, a list of ``[lat, lon]`` pairs (a single simple ring).
  Handled by stdlib ray casting — the project stays installable in ten seconds.
- A GeoJSON geometry dict (``Polygon`` / ``MultiPolygon``, coordinates in
  ``[lon, lat]`` order), which is how real Natura 2000 marine / WDPA layers ship.
  These carry holes and multiple parts that ray casting over a flat ring cannot
  represent, so they are delegated to shapely. shapely is an *optional* import:
  it is only required once a zone's ``polygon`` is such a dict.
"""

import math


def _shapely_shape():
    """Return shapely's ``shape`` builder, or raise a clear install hint.

    Cached on the function object so the import is attempted once.
    """
    if not hasattr(_shapely_shape, "_fn"):
        try:
            from shapely.geometry import shape
            _shapely_shape._fn = shape
        except ImportError as exc:  # pragma: no cover - exercised only w/o shapely
            _shapely_shape._fn = exc
    fn = _shapely_shape._fn
    if isinstance(fn, ImportError):
        raise RuntimeError(
            "This zone uses a GeoJSON geometry (real Natura 2000 / WDPA data), "
            "which needs shapely. Install it with: pip install shapely"
        ) from fn
    return fn


def point_in_polygon(lat: float, lon: float, polygon) -> bool:
    """True if (lat, lon) lies inside the polygon.

    A GeoJSON geometry dict is tested with shapely (respecting holes and
    multipart geometries); a boundary point counts as inside. A list of
    ``[lat, lon]`` pairs uses the stdlib ray cast.
    """
    if isinstance(polygon, dict):
        shape = _shapely_shape()  # raises the clear install hint if absent
        from shapely.geometry import Point
        # GeoJSON is (lon, lat); shapely is (x, y) = (lon, lat).
        return shape(polygon).covers(Point(lon, lat))

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


def centroid(polygon) -> tuple:
    """Centroid as (lat, lon).

    For a GeoJSON geometry this is the true area centroid (shapely); for a
    ``[lat, lon]`` ring it is the vertex average, which the demo relies on.
    """
    if isinstance(polygon, dict):
        c = _shapely_shape()(polygon).centroid
        return (c.y, c.x)  # shapely (x, y) = (lon, lat)
    lats = [p[0] for p in polygon]
    lons = [p[1] for p in polygon]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _demo() -> None:
    """Self-check: ray cast on the legacy ring, plus the GeoJSON path.

    Run: python src/geo.py
    """
    # Legacy [lat, lon] ring — the demo/test path, no dependency needed.
    ring = [[36.6, -7.2], [36.6, -6.9], [36.85, -6.9], [36.85, -7.2]]
    assert point_in_polygon(36.7, -7.0, ring) is True
    assert point_in_polygon(36.7, -6.0, ring) is False
    clat, clon = centroid(ring)
    assert abs(clat - 36.725) < 1e-9 and abs(clon - -7.05) < 1e-9

    # GeoJSON path — a square with a hole, exactly what real MPA layers carry.
    holed = {
        "type": "Polygon",
        "coordinates": [
            [[-7.2, 36.6], [-6.9, 36.6], [-6.9, 36.85], [-7.2, 36.85], [-7.2, 36.6]],
            [[-7.1, 36.7], [-7.0, 36.7], [-7.0, 36.8], [-7.1, 36.8], [-7.1, 36.7]],
        ],
    }
    try:
        _shapely_shape()  # is shapely installed here?
    except RuntimeError:
        # No shapely: the dict path must fail loudly, not silently mis-classify.
        for call in (lambda: point_in_polygon(36.7, -7.05, holed),
                     lambda: centroid(holed)):
            try:
                call()
                raise AssertionError("expected a shapely-required error")
            except RuntimeError:
                pass
        print("geo self-check: ray cast OK; GeoJSON path raises clearly (no shapely)")
        return

    assert point_in_polygon(36.62, -7.15, holed) is True    # in the ring
    assert point_in_polygon(36.75, -7.05, holed) is False   # in the hole
    assert point_in_polygon(36.5, -7.05, holed) is False    # outside
    multi = {"type": "MultiPolygon", "coordinates": [holed["coordinates"][:1],
             [[[-6.5, 36.4], [-6.3, 36.4], [-6.3, 36.5], [-6.5, 36.5], [-6.5, 36.4]]]]}
    assert point_in_polygon(36.45, -6.4, multi) is True     # second part
    print("geo self-check: ray cast + GeoJSON holes/multipart OK (shapely present)")


if __name__ == "__main__":
    _demo()
