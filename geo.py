"""Utilidades geoespaciales minimas, sin dependencias externas.

Cuando pasemos a poligonos reales (Natura 2000 marino, WDPA) conviene
sustituir esto por shapely + geopandas. De momento con ray casting sobra
y mantiene el prototipo instalable en 10 segundos.
"""

import math


def punto_en_poligono(lat: float, lon: float, poligono: list) -> bool:
    """Ray casting. El poligono es una lista de pares [lat, lon]."""
    dentro = False
    n = len(poligono)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = poligono[i]
        lat_j, lon_j = poligono[j]
        if (lon_i > lon) != (lon_j > lon):
            corte = (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i) + lat_i
            if lat < corte:
                dentro = not dentro
        j = i
    return dentro


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia haversine en kilometros."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return round(2 * r * math.asin(math.sqrt(a)), 2)


def centroide(poligono: list) -> tuple:
    lats = [p[0] for p in poligono]
    lons = [p[1] for p in poligono]
    return (sum(lats) / len(lats), sum(lons) / len(lons))
