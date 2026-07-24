"""Environmental context gate (agentic loop, Step 1).

Angula (European eel) is fished on DARK nights around SPRING tides, in estuaries
and river mouths. Before spending a satellite tasking on a scene, the agent asks:
were the conditions even propitious? This module answers that from the scene
timestamp alone, deterministically — no model, no network, no dependency.

WHAT THIS IS AND IS NOT:
This is a SCANNING-PRIORITY signal: it helps decide whether and where to look
(Step 1), and it is reported at scene level. It is NEVER a per-vessel indicator
and never contributes to any vessel's score. A dark spring-tide night is not
evidence against any individual boat; treating it as such would be exactly the
kind of guilt-by-context this system is built to avoid. The duty of caution
that governs the per-vessel engine (analysis.py) governs here too.

WHAT IS HONESTLY COMPUTED vs. WHAT NEEDS REAL DATA:
- Moon illumination and phase are astronomy: computed here, exactly.
- Spring/neap tendency follows directly from lunar phase (spring near new and
  full moon): also astronomy, computed here.
- The actual high-water CLOCK TIME and local night window depend on a tide
  station and an ephemeris for the specific estuary. Those are a real-data
  plug-in point (like the live sources noted in data.py), NOT faked here. We
  report the spring/neap tendency, which is what lunar phase can honestly tell
  us, and flag the high-water timing as a cross-check the authority must supply.
"""

import math
from datetime import datetime, timezone

# A known reference new moon (2000-01-06 18:14 UTC) and the mean synodic month.
# Good to well under a day over the decades that matter here — ample for a
# darkness/spring-tide gate whose output is a coarse suitability label.
_REF_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
_SYNODIC_DAYS = 29.530588853

# Illumination at or below this is a "dark" night in the sense that matters for
# angula. Tunable per jurisdiction via config["environment"]["dark_illumination"].
_DEFAULT_DARK_ILLUMINATION = 0.25

_PHASE_NAMES = [
    "new moon", "waxing crescent", "first quarter", "waxing gibbous",
    "full moon", "waning gibbous", "last quarter", "waning crescent",
]


def _parse(timestamp: str) -> datetime:
    if not isinstance(timestamp, str):
        raise ValueError(f"scene timestamp is missing or not a string: {timestamp!r}")
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"scene timestamp is invalid: {timestamp!r}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _phase_fraction(dt: datetime) -> float:
    """Position in the lunar cycle: 0.0 = new moon, 0.5 = full moon."""
    days = (dt - _REF_NEW_MOON).total_seconds() / 86400.0
    return (days % _SYNODIC_DAYS) / _SYNODIC_DAYS


def angula_conditions(timestamp: str, config: dict | None = None) -> dict:
    """Assess how propitious a scene's date is for angula poaching.

    Returns a scene-level dictionary. It ranks days/zones for scanning; it says
    nothing about any individual vessel.
    """
    config = config or {}
    dark_threshold = (config.get("environment", {})
                      .get("dark_illumination", _DEFAULT_DARK_ILLUMINATION))

    dt = _parse(timestamp)
    phase = _phase_fraction(dt)

    # Illumination: 0 at new moon, 1 at full moon.
    illumination = (1 - math.cos(2 * math.pi * phase)) / 2
    darkness = 1 - illumination

    # Spring/neap: tidal range peaks at new and full moon (sun and moon aligned),
    # troughs at the quarters. cos(4*pi*phase) is +1 at new/full, -1 at quarters.
    spring_index = (math.cos(4 * math.pi * phase) + 1) / 2

    phase_name = _PHASE_NAMES[int((phase * 8 + 0.5)) % 8]

    dark = illumination <= dark_threshold
    spring = spring_index >= 0.5

    # Darkness is the dominant, most discriminating factor for angula ("noches
    # oscuras"); a spring tide corroborates it. New moon is the peak because it
    # delivers both at once. This rule is transparent and deliberately coarse: it
    # orders which nights to task, it is not a probability of poaching.
    if dark and spring:
        suitability = "high"
        rationale = (f"{phase_name}: dark night (illumination {illumination:.0%}) "
                     f"coinciding with spring tides — peak conditions for angula.")
    elif dark or spring:
        suitability = "moderate"
        rationale = (f"{phase_name}: "
                     + ("a dark night" if dark else "spring tides")
                     + (", but not both together." if not (dark and spring) else "."))
    else:
        suitability = "low"
        rationale = (f"{phase_name}: bright night (illumination {illumination:.0%}) "
                     f"near neap tides — unfavourable for angula.")

    return {
        "scene_timestamp": timestamp,
        "moon_phase": phase_name,
        "moon_illumination": round(illumination, 3),
        "darkness_favourability": round(darkness, 3),
        "spring_tide_tendency": round(spring_index, 3),
        "suitability": suitability,
        "rationale": rationale,
        "role": ("Scanning-priority signal only. It ranks days and zones for "
                 "satellite tasking; it is NOT a per-vessel indicator and never "
                 "contributes to any vessel's score."),
        "cross_check_required": (
            "High-water clock time and the local night window depend on the "
            "estuary's tide station and ephemeris; supply these from the "
            "authority's own tide tables to confirm the operative window."),
    }


def _demo() -> None:
    # Known new moon (2024-01-11) → dark + spring → high suitability.
    new = angula_conditions("2024-01-11T02:00:00Z")
    assert new["moon_illumination"] < 0.1, new
    assert new["suitability"] == "high", new
    assert new["spring_tide_tendency"] > 0.9, new

    # Known full moon (2024-01-25) → bright, but still spring tides → moderate.
    full = angula_conditions("2024-01-25T18:00:00Z")
    assert full["moon_illumination"] > 0.9, full
    assert full["spring_tide_tendency"] > 0.9, full
    assert full["suitability"] == "moderate", full

    # First quarter (2024-01-18) → half-lit, neap tides → low suitability.
    quarter = angula_conditions("2024-01-18T03:53:00Z")
    assert quarter["spring_tide_tendency"] < 0.15, quarter
    assert quarter["suitability"] == "low", quarter

    # A malformed timestamp must fail loudly, like the rest of the engine.
    for bad in ("not-a-date", None):
        try:
            angula_conditions(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass

    print("environment self-check passed:",
          f"new={new['suitability']}, full={full['suitability']}, "
          f"quarter={quarter['suitability']}")


if __name__ == "__main__":
    _demo()
