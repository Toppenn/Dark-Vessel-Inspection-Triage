# Sample output

Full, unedited output of the demo path, regenerated from the committed demo data. The
README quotes a short excerpt from section 1; this file holds all three stages in full.

Reproduce it with:

```bash
python src/main.py --cross-reference-only   # section 1 only, no API key needed
python src/main.py                          # all three sections, needs NVIDIA_API_KEY
```

Section 1 is deterministic and will match byte for byte. Sections 2 and 3 are model output:
the wording varies between runs, the facts do not — that is what the validator enforces.

---

## 1. Deterministic cross-reference

`python src/main.py --cross-reference-only`

```
Detections analysed: 13
AIS carriage threshold applied: 15.0 m (length uncertainty +/-2.0 m)
Environmental context (waxing crescent): angula suitability OUT_OF_SEASON
  (scanning-priority signal, not a vessel indicator)
  outside the angula campaign window (10-10 to 03-31): the fishery is closed, so
  lunar conditions do not raise scanning priority. Moon figures reported as computed.
Active closure: Northern Fishing Ground - seasonal spawning closure (spawning season)
Patrol base: Port of Cadiz patrol base (demo) (radius 120 km)

Classification summary:
  high_priority      3
  medium_priority    4
  fixed_structure    1
  no_indicators      3
  ais_not_applicable 2

  D-010  -> HIGH_PRIORITY | 2 independent indicator(s) concur | 38.0 km from base
    Pos 36.44, -6.7 | length 26.5 m | AIS: unmatched (dark) | likely gear: bottom_trawl
    Zone: Islote Sur Integral Reserve (integral_reserve)
    Indicator: radar-estimated length 26.5 m is above the 15.0 m threshold beyond
               sensor uncertainty and no AIS broadcast was matched; if this is a Union
               fishing vessel exceeding 15.0 m LOA, the AIS carriage and operation
               requirement is potentially concerned (Article 10(1), Council Regulation
               (EC) No 1224/2009, as amended by Regulation (EU) 2023/2842)
    Indicator: presence with a contextual fishing indication inside integral_reserve
               'Islote Sur Integral Reserve' (RES-03) where all fishing gear is prohibited (activity per
               contextual classifier, non-observational)
      +40  no AIS broadcast matched while the carriage requirement is potentially engaged
      +30  contextual fishing indication where all gear is prohibited (RES-03)

  D-001  -> MEDIUM_PRIORITY | 1 independent indicator(s) concur | 71.04 km from base
    Pos 36.72, -7.05 | length 34.0 m | AIS: unmatched (dark) | likely gear: bottom_trawl
    Zone: Bajo de los Corales Marine Protected Area (marine_protected_area)
    Indicator: radar-estimated length 34.0 m is above the 15.0 m threshold beyond
               sensor uncertainty and no AIS broadcast was matched; ...
    Context (not an indicator): radar-inferred gear class 'bottom_trawl' would be
               prohibited in marine_protected_area 'Bajo de los Corales Marine Protected
               Area' (MPA-01), but gear inference for an unmatched detection is
               enrichment, not observation - context only, to be verified on inspection

  D-005  -> MEDIUM_PRIORITY | 1 independent indicator(s) concur | 44.02 km from base
    Pos 36.49, -6.78 | length 9.5 m | AIS: unmatched (dark) | likely gear: small_scale
    Zone: Islote Sur Integral Reserve (integral_reserve)
    Indicator: presence with a contextual fishing indication inside integral_reserve
               'Islote Sur Integral Reserve' (RES-03) where all fishing gear is prohibited
    AIS note: Below the AIS carriage threshold: absence of an AIS broadcast is not an
              indicator. Other indicators, if any, remain.
      +30  contextual fishing indication where all gear is prohibited (RES-03)

--- PATROL SEQUENCE (priority, then distance from base) ---
  D-010  high_priority      38.0 km  (36.44, -6.7)
  D-004  high_priority     40.77 km  (36.47, -6.74)
  D-006  high_priority     78.21 km  (37.02, -6.92)
  D-005  medium_priority   44.02 km  (36.49, -6.78)
  D-002  medium_priority   68.15 km  (36.71, -7.02)
  D-001  medium_priority   71.04 km  (36.72, -7.05)
  D-008  medium_priority  102.56 km  (36.3, -7.4)

--- BELOW CANDIDATE THRESHOLD (listed, not actioned) ---
  D-013 (fixed_structure, score 0): no indicators
  D-003 (no_indicators, score 0): no indicators
  D-009 (no_indicators, score 0): no indicators
  D-012 (no_indicators, score 0): no indicators

--- AIS INDICATOR SUPPRESSED (duty of caution) ---
  D-005 (medium_priority): Below the AIS carriage threshold: absence of an AIS
        broadcast is not an indicator. Other indicators, if any, remain.
  D-007 (ais_not_applicable): ... The estimated length is within sensor uncertainty of
        the 12.0 m VMS threshold, so a VMS cross-check may or may not apply; the
        authority can settle this from its own records.

--- ATTRIBUTED TO CHARTED FIXED INFRASTRUCTURE (false-positive guard, duty of caution) ---
  D-013 -> FIX-01 (fixed_platform): Coincides with charted fixed structure FIX-01
        (fixed_platform). The radar return is attributable to infrastructure, so no
        dark-vessel candidate is raised; verify on inspection that no vessel is
        operating alongside it.
```

Five things to read here. **D-005** is below the threshold, has its AIS indicator
suppressed and explained, and is still a candidate on a zone indicator — the duty of caution
removes one piece of evidence, not the vessel. **D-001** shows the gear class demoted to
*context, not an indicator*: gear cannot be inferred from a radar return on an unmatched
detection, so it does not score. **D-013** is a charted platform, not a boat: the engine
attributes the return to infrastructure, raises no candidate, and says which structure and
why. **D-003, D-009 and D-012** are printed even though nothing will be done about them,
because reporting only what we act on would hide from the reader that they were considered.
And the patrol sequence reorders the list by what a patrol vessel can actually reach.

The environmental line at the top is the scanning-priority gate, and the demo scene shows it
doing the thing it exists for: 18 July is a dark waxing-crescent night, but the angula
campaign is closed, so the label is `OUT_OF_SEASON` rather than a high score on the strength
of the moon alone.

## 2. Analyst agent

`python src/main.py`

```
  1. D-010 [ais+zone, confidence high]
     High-priority candidate with two independent indicators: radar-estimated length
     26.5 m exceeds AIS threshold (no AIS match) and contextual fishing indication
     inside integral reserve RES-03 where all gear is prohibited.
  4. D-005 [zone, confidence medium]
     Medium-priority candidate; AIS indicator suppressed due to length below threshold,
     but single zone indicator: contextual fishing indication inside integral reserve
     RES-03 where all gear is prohibited.

AIS not applicable (indicator suppressed):
  - D-005: estimated length 9.5 m is below the 15.0 m AIS carriage threshold; absence
    of AIS broadcast is not an indicator per Article 10(1).

Stated limitations:
  - Cannot verify vessel flag state, actual gear deployed, or whether any AIS
    suppression is lawfully derogated under Article 10(2).
  - Radar-derived length estimates have uncertainty; true length may fall below or
    above the AIS threshold.
  - Contextual fishing indications are non-observational and require corroboration
    during inspection.
  - The analysis does not account for possible AIS switch-off notifications that would
    render a dark vessel lawfully compliant.
```

The agent reproduces the suppression rule in its own words and states, unprompted, the four
things it cannot know — including the lawful derogation that could explain the very darkness
it is reporting.

## 3. Writer agent and validation

```
  [HIGH] D-006 - 37.02, -6.92
    - gear 'bottom_trawl' (fleet registry) prohibited in seasonal_closure 'Northern
      Fishing Ground - seasonal spawning closure' (CLS-02)
    - contextual classifier indicates likely fishing activity (non-observational)
      during active closure (spawning season) (CLS-02)
    Regulation: Bottom trawl prohibited in Northern Fishing Ground - seasonal spawning
                closure (CLS-02) (active closure)
    Action:     Board and verify gear and documentation, 78.21 km from base
    Caveat:     The vessel may be transiting through the closure without engaging in
                fishing activity, or the registry gear may not be currently deployed.

  [MEDIUM] D-005 - 36.49, -6.78
    - presence with a contextual fishing indication inside integral_reserve 'Islote Sur
      Integral Reserve' (RES-03) where all fishing gear is prohibited (activity per
      contextual classifier, non-observational)
    Regulation: All fishing gear prohibited in Islote Sur Integral Reserve (RES-03)
    Action:     Board and verify gear and documentation, 44.02 km from base
    Caveat:     The vessel is below the 15 m AIS carriage threshold; lack of AIS
                broadcast is not indicative of non-compliance. The contextual fishing
                indication inside the integral reserve may be inaccurate; verify on site.

========================================================================
OUTPUT VALIDATION
========================================================================
Output validation: no issues.
```

D-006 is broadcasting, and its brief cites only the closure and the gear prohibition — never
the carriage requirement, which is not engaged for a vessel that is transmitting. D-005's
brief states in the caveat why its silence carries no weight. Neither property is left to
the model's goodwill: both are checked before the report is printed.