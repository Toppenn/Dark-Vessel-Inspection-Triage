"""Environmental context gate (agentic loop, Step 1).

Angula (glass eel, juvenile European eel) is fished in season, on DARK nights,
around SPRING tides, in estuaries and river mouths. Before spending a satellite
tasking on a scene, the agent asks: were the conditions even propitious? This
module answers that from the scene timestamp alone, deterministically — no
model, no network, no dependency.

WHAT THIS IS AND IS NOT
This is a SCANNING-PRIORITY signal: it helps decide whether and where to look
(Step 1), and it is reported at scene level. It is NEVER a per-vessel indicator
and never contributes to any vessel's score. A dark spring-tide night in season
is not evidence against any individual boat; treating it as such would be
exactly the kind of guilt-by-context this system is built to avoid. The duty of
caution that governs the per-vessel engine (analysis.py) governs here too.

SCOPE LIMIT — THE SENSOR THAT WOULD SEE AN ANGULA BOAT IS NOT THIS ONE
Angula is fished with cedazo from the shore or from small craft, inside
estuaries and river mouths. Those boats sit far below Sentinel-1's ~15 m
detection floor, whereas the detections this repository reasons about are 9-31 m
vessels in open water. This gate therefore ranks scanning priority for estuary
tasking: it says which nights are worth looking at, with whatever sensor is
appropriate. SAR vessel detection is not that sensor, and nothing here should be
read as implying that an angula boat would appear in a Sentinel-1 scene. The
limitation is written down rather than left for the framing to obscure.

WHAT IS HONESTLY COMPUTED vs. WHAT NEEDS REAL DATA
- Moon illumination and phase are astronomy: computed here, exactly.
- Spring/neap tendency follows directly from lunar phase (spring near new and
  full moon): also astronomy, computed here.
- The SEASON is regulatory, not astronomical. It is configurable because each
  autonomous community opens its own campaign — see _DEFAULT_SEASON.
- The actual high-water CLOCK TIME and local night window depend on a tide
  station and an ephemeris for the specific estuary. Those are a real-data
  plug-in point (like the live sources noted in data.py), NOT faked here. We
  report the spring/neap tendency, which is what lunar phase can honestly tell
  us, and flag the high-water timing as a cross-check the authority must supply.
"""

import math
from datetime import date, datetime, timezone

# A known reference new moon (2000-01-06 18:14 UTC) and the mean synodic month.
# Good to well under a day over the decades that matter here — ample for a
# darkness/spring-tide gate whose output is a coarse suitability label.
_REF_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
_SYNODIC_DAYS = 29.530588853

# Illumination at or below this is a "dark" night in the sense that matters for
# angula. Tunable per jurisdiction via config["environment"]["dark_illumination"].
_DEFAULT_DARK_ILLUMINATION = 0.25

# The angula campaign is opened by each autonomous community and its dates move
# between campaigns, so this default is a starting point, not a legal fact. It
# follows the Cantabrian campaign (10 October to 31 March). Asturias opens on
# 1 November and closes on the same date; the Basque Country anchors its season
# to the October and March new moons. March is a core month in every published
# window, so a default that ends in February would call the tail of the campaign
# closed. Set config["environment"]["season"] to the window published for the
# jurisdiction being analysed, and treat this default as a placeholder in
# exactly the way length_sigma_m is one.
_DEFAULT_SEASON = {"start": "10-10", "end": "03-31"}

_PHASE_NAMES = [
    "new moon", "waxing crescent", "first quarter", "waxing gibbous",
    "full moon", "waning gibbous", "last quarter", "waning crescent",
]

# Suitability labels. Out-of-season is its own state rather than a low score:
# "the fishery is closed" is a different statement from "the moon is wrong".
HIGH = "high"
MODERATE = "moderate"
LOW = "low"
OUT_OF_SEASON = "out_of_season"


def _parse(timestamp: str) -> datetime:
    if not isinstance(timestamp, str):
        raise ValueError(f"scene timestamp is missing or not a string: {timestamp!r}")
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"scene timestamp is invalid: {timestamp!r}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_month_day(value, field: str) -> tuple:
    """Parse an "MM-DD" season bound into (month, day), failing loudly.

    A season window silently misread would move the gate by months, so this
    follows the engine's rule: decisive configuration fails loudly or not at all.
    """
    if not isinstance(value, str):
        raise ValueError(f"season {field} must be an 'MM-DD' string, got {value!r}")
    try:
        month_text, day_text = value.split("-")
        month, day = int(month_text), int(day_text)
        date(2000, month, day)          # 2000 is a leap year, so 02-29 is valid
    except ValueError as exc:
        raise ValueError(
            f"season {field} must be a valid 'MM-DD' date, got {value!r}") from exc
    return month, day


def _phase_fraction(dt: datetime) -> float:
    """Position in the lunar cycle: 0.0 = new moon, 0.5 = full moon."""
    days = (dt - _REF_NEW_MOON).total_seconds() / 86400.0
    return (days % _SYNODIC_DAYS) / _SYNODIC_DAYS


def _in_season(dt: datetime, season: dict) -> bool:
    """Is the scene date inside the campaign window?

    The window crosses the year boundary (November to February), so a naive
    start <= today <= end is wrong for every date in it: it would return False
    for December and January, which is most of the season.
    """
    start = _parse_month_day(season.get("start"), "start")
    end = _parse_month_day(season.get("end"), "end")
    today = (dt.month, dt.day)

    if start <= end:                        # window sits inside one calendar year
        return start <= today <= end
    return today >= start or today <= end   # window wraps the year boundary


def angula_conditions(timestamp: str, config: dict | None = None) -> dict:
    """Assess how propitious a scene's date is for angula poaching.

    Returns a scene-level dictionary. It ranks days and zones for scanning; it
    says nothing about any individual vessel.
    """
    config = config or {}
    env_config = config.get("environment", {})
    dark_threshold = env_config.get("dark_illumination",
                                    _DEFAULT_DARK_ILLUMINATION)
    season = env_config.get("season", _DEFAULT_SEASON)

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
    in_season = _in_season(dt, season)

    # Season first. It is the filter anyone in the sector applies before looking
    # at the moon at all: outside the campaign there is no legal fishery whose
    # scanning to prioritise, however dark the night. The lunar figures are still
    # reported as computed values — they are astronomy and remain true — but they
    # cannot produce a suitability label out of season.
    if not in_season:
        suitability = OUT_OF_SEASON
        rationale = (f"outside the angula campaign window "
                     f"({season.get('start')} to {season.get('end')}): the "
                     f"fishery is closed, so lunar conditions do not raise "
                     f"scanning priority. Moon figures reported as computed.")
    elif dark and spring:
        suitability = HIGH
        rationale = (f"{phase_name}: dark night (illumination {illumination:.0%}) "
                     f"coinciding with spring tides, in season — peak conditions "
                     f"for angula.")
    elif dark or spring:
        suitability = MODERATE
        rationale = (f"{phase_name}, in season: "
                     + ("a dark night" if dark else "spring tides")
                     + ", but not both together.")
    else:
        suitability = LOW
        rationale = (f"{phase_name}: bright night (illumination {illumination:.0%}) "
                     f"near neap tides — unfavourable for angula.")

    return {
        "scene_timestamp": timestamp,
        "in_season": in_season,
        "season_window": f"{season.get('start')} to {season.get('end')}",
        "moon_phase": phase_name,
        "moon_illumination": round(illumination, 3),
        "darkness_favourability": round(darkness, 3),
        "spring_tide_tendency": round(spring_index, 3),
        "suitability": suitability,
        "rationale": rationale,
        "role": ("Scanning-priority signal only. It ranks days and zones for "
                 "satellite tasking; it is NOT a per-vessel indicator and never "
                 "contributes to any vessel's score."),
        "sensor_scope": (
            "Angula is fished from shore or small craft inside estuaries, below "
            "SAR's detection floor. This gate prioritises estuary tasking; "
            "Sentinel-1 vessel detection is not the sensor that would observe an "
            "angula boat."),
        "cross_check_required": (
            "High-water clock time and the local night window depend on the "
            "estuary's tide station and ephemeris; supply these from the "
            "authority's own tide tables to confirm the operative window."),
    }


def _demo() -> None:
    season = {"environment": {"season": {"start": "11-01", "end": "02-28"}}}

    # Known new moon (2024-01-11), in season → dark + spring → high suitability.
    new = angula_conditions("2024-01-11T02:00:00Z", season)
    assert new["moon_illumination"] < 0.1, new
    assert new["suitability"] == HIGH, new
    assert new["spring_tide_tendency"] > 0.9, new

    # Known full moon (2024-01-25) → bright, but still spring tides → moderate.
    full = angula_conditions("2024-01-25T18:00:00Z", season)
    assert full["moon_illumination"] > 0.9, full
    assert full["spring_tide_tendency"] > 0.9, full
    assert full["suitability"] == MODERATE, full

    # First quarter (2024-01-18) → half-lit, neap tides → low suitability.
    quarter = angula_conditions("2024-01-18T03:53:00Z", season)
    assert quarter["spring_tide_tendency"] < 0.15, quarter
    assert quarter["suitability"] == LOW, quarter

    # July new moon: the same lunar conditions as the January one, but the
    # fishery is closed. The label must not be "high".
    july = angula_conditions("2024-07-05T22:00:00Z", season)
    assert july["suitability"] == OUT_OF_SEASON, july
    assert july["in_season"] is False, july

    # A malformed timestamp must fail loudly, like the rest of the engine.
    for bad in ("not-a-date", None):
        try:
            # The None case is deliberate: a missing timestamp must raise, not
            # be quietly treated as "now". The annotation says str, which is the
            # contract; the check is that violating it fails loudly.
            angula_conditions(bad, season)  # type: ignore[arg-type]
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass

    # So must a malformed season window.
    try:
        angula_conditions("2024-01-11T02:00:00Z",
                          {"environment": {"season": {"start": "13-45",
                                                      "end": "02-28"}}})
        raise AssertionError("expected ValueError for an invalid season bound")
    except ValueError:
        pass

    print("environment self-check passed:",
          f"new={new['suitability']}, full={full['suitability']}, "
          f"quarter={quarter['suitability']}, july={july['suitability']}")


if __name__ == "__main__":
    _demo()
