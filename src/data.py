"""Data loading.

Right now this reads local synthetic JSON files. To go live, only these two
functions need reimplementing — as long as they return the same shape, the
rest of the system does not change.

Planned real sources:
  detections -> Global Fishing Watch, "Vessel detections from Sentinel-1 SAR"
                (public API and download portal), or the xView3 benchmark
  zones      -> Natura 2000 marine, WDPA, marine reserves of fishing interest,
                seasonal closures published in official bulletins
  raw imagery -> Copernicus Data Space Ecosystem (Sentinel-1), only if we
                choose to run our own detector instead of using existing
                detections
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "demo_data"


def load_zones(filename: str = "zones.json") -> dict:
    """Regulatory layer: zones, prohibited gear, closures and configuration."""
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def load_detections(filename: str = "detections.json") -> dict:
    """Radar detections for one scene, including AIS matching."""
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return json.load(f)
