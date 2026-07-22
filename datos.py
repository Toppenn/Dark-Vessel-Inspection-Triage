"""Carga de datos.

Hoy lee JSON locales sinteticos. Al conectar las fuentes reales solo hay que
reimplementar estas funciones manteniendo el formato de salida; el resto del
sistema no se entera.

Fuentes reales previstas:
  - detecciones -> Global Fishing Watch, dataset "Vessel detections from
                   Sentinel-1 SAR" (API y portal de descarga) / xView3
  - zonas       -> Natura 2000 marino, WDPA, reservas marinas de interes
                   pesquero, vedas publicadas en boletines oficiales
  - escenas     -> Copernicus Data Space Ecosystem (Sentinel-1) si se procesa
                   la imagen cruda en lugar de usar detecciones ya hechas
"""

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "datos_demo"


def cargar_zonas(nombre_fichero: str = "zonas.json") -> dict:
    """Capa legal: zonas reguladas, artes prohibidas, vedas y configuracion."""
    with open(DIR_DATOS / nombre_fichero, encoding="utf-8") as f:
        return json.load(f)


def cargar_detecciones(nombre_fichero: str = "detecciones.json") -> dict:
    """Detecciones radar de una escena, con emparejamiento AIS."""
    with open(DIR_DATOS / nombre_fichero, encoding="utf-8") as f:
        return json.load(f)
