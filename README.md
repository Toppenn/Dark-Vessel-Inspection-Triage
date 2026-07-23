# Dark Vessel Inspection Triage

**NVIDIA Open Models Codefest 2026 — team submission**

An agentic decision-support system that turns open satellite radar detections into
prioritised, explainable inspection briefs for European fisheries control authorities.

---

## The problem

Illegal, unreported and unregulated (IUU) fishing is a significant EU policy problem, and
Spain operates one of the largest fishing fleets in the Union. Fishing vessels carry AIS
transponders that broadcast their position — but a transponder can be switched off.
Research using Copernicus Sentinel-1 radar has found that a large share of fishing vessels
at sea are not broadcasting their positions, and that non-broadcasting vessels are more
frequently associated with illicit activity than those that do broadcast.

Inspection capacity is finite. Patrol vessels and aircraft cannot cover an entire sea
area. The operational question is not "who is guilty" — it is **where should the next
inspection go**.

---

## What the system does

Given radar vessel detections for a sea area and the applicable regulatory layers, the
system:

1. **Cross-references** every detection against AIS matching, marine protected area
   boundaries, seasonal closures and permitted fishing gear.
2. **Scores** each detection with a fully itemised breakdown — every point awarded has a
   stated reason, and no point is ever awarded without a concrete indicator. No black box.
3. **Sequences** the candidates for a patrol: priority first, then distance from the
   patrol base, so the ranking is directly actionable.
4. **Reasons** over the scene as a whole: ranks inspection candidates, identifies spatial
   clustering, and declares what the analysis cannot know.
5. **Drafts inspection briefs** stating the indicators, the regulation concerned, the
   suggested action, and — deliberately — the innocent explanation that could account for
   the indicator.

---

## Duty of caution

**A vessel not broadcasting AIS is not automatically an offender.** Vessels at or below
the legal length threshold are not required to broadcast at all. For those vessels the
system suppresses the **AIS indicator** — and only that indicator. Every other indicator
(prohibited gear, an active seasonal closure) is assessed exactly as for any other
vessel. A small dark vessel apparently fishing inside an integral reserve is still an
inspection candidate, on the strength of its zone indicators alone; a small dark vessel
with nothing else against it scores zero and is never prioritised. Suppressing the
vessel instead of the indicator would be the opposite failure: under-reporting.

This is not a technical footnote. It is the design decision that separates a legitimate
triage tool from a machine that generates suspicion without basis. Throughout, the system
speaks of *indicators justifying inspection*, never of *offences*. A human officer always
decides.

The threshold is not arbitrary: Article 10(1) and (2), Council Regulation (EC)
No 1224/2009, as amended by Regulation (EU) 2023/2842, is the legal basis used throughout.
Article 10(1) requires Union fishing vessels **exceeding** 15 m length overall to be
fitted with and maintain in operation an AIS. Three consequences are implemented
literally:

- **"Exceeding" is strict.** A vessel of exactly 15.0 m is not covered, and the system
  never claims that 15.0 exceeds 15.0.
- **The obligation binds Union fishing vessels** — and a dark vessel's flag state is
  unknown by definition. The AIS indicator is therefore phrased conditionally: *"if this
  is a Union fishing vessel exceeding 15 m LOA, the AIS carriage and operation
  requirement is potentially concerned (Art. 10(1))"*. Every record carries a
  `jurisdiction` field: the flag for AIS-matched vessels, `"unknown"` for the rest.
- **A dark vessel may be lawfully dark.** Article 10(2) (introduced by the 2023 revision)
  lets the master switch off AIS where crew safety or security is imminently at risk —
  and requires the switch-off and its reason to be notified. The brief's caveat is
  therefore a verifiable action, not a shrug: *check whether an AIS switch-off
  notification was filed for this time window (Art. 10(2))*. The exact paragraph
  numbering should be confirmed against the consolidated text of the amended regulation.

Additionally, since January 2026 fishing vessels of 12 m and over must carry an
operational VMS. For a small dark vessel at or above that length the correct statement is
not "unobservable" but: *absence of AIS is not an indicator; the appropriate cross-check
is VMS, which the authority already holds*. The engine says exactly that in the record's
AIS note.

The threshold, the length-uncertainty band and the VMS threshold are configurable
parameters in `demo_data/zones.json`, so they can be set to the correct legal values per
jurisdiction and audited independently of the code.

The duty runs in both directions. The system must not under-report either: a vessel above
the threshold that is not broadcasting is potentially in breach of the carriage
requirement itself, wherever it is, and that provision is named explicitly rather than
reported as "no regulation concerned". The validator enforces the same symmetry on the
model: a high-priority record without a brief blocks the report, just as an invented
accusation does.

This property is tested, not merely documented — see `src/test_caution.py`.

---

## Scoring

Scoring obeys one hard invariant, enforced by test: **score > 0 if and only if the record
has at least one concrete indicator.** Presence inside a regulated zone scores nothing by
itself — only a concrete violation does (prohibited gear, apparent fishing during an
active closure, or the carriage requirement potentially engaged). There is no
"a provision is concerned" bonus: that was double counting, and it is gone.

The score is an internal ordering aid. It is presented **ordinally** — high or medium
priority — and in prose as *"N independent indicators concur"*, never as a headline
number. Weights live in `demo_data/zones.json` (`score_weights`), are transparent, and
are not yet calibrated against enforcement outcomes: they order candidates, they are not
probabilities of infringement.

Two honesty rules shape what counts as an indicator at all:

- **Length uncertainty.** The radar length estimate carries sensor error and the legal
  threshold sits near the detection floor. AIS applicability is therefore three-state:
  firmly above (`length − k·σ > threshold`, full indicator), near threshold
  (`length + k·σ > threshold`, a degraded indicator explicitly labelled *"length near
  threshold, inconclusive"*, worth fewer points), and not applicable (AIS indicator
  suppressed). `length_sigma_m` is a configurable placeholder pending calibration
  against Paolo et al. 2024 — a known limitation.
- **Source honesty.** The fishing-behaviour score in the upstream data comes from a
  contextual classifier, not from observed movement, so it is labelled
  *"contextual classifier indicates likely fishing activity (non-observational)"* and
  only ever corroborates an existing indicator. Likewise, for an unmatched detection the
  inferred gear class is enrichment, not observation: in a zone that prohibits specific
  gear it is reported as **context, not an indicator** (for AIS-matched vessels the gear
  class comes from the fleet registry and remains a valid indicator).

Only high- and medium-priority records are inspection candidates; a vessel without
indicators is not a candidate and is never presented to the agents as one.

---

## Architecture

```
GFW / Sentinel-1 detections ─┐
Marine protected areas       ├─> deterministic ──> analyst agent ──> writer agent ──> briefs
Seasonal closures            │   cross-reference     (Nemotron)        (Nemotron)
Gear restrictions           ─┘   analysis.py              │                │
                                 auditable, no LLM        └── validated ───┘
                                                              in code, blocking
```

**Positions, geometry and scores are computed deterministically and are never generated by
the model.** In an enforcement file the figures must be reproducible and auditable. The
open models do what they are genuinely good at: interpreting context, prioritising, and
writing for a human reader.

**Why open models matter here.** Because the weights are open, the system can be deployed
inside the authority's own environment — operational data never leaves it — and its
reasoning can be inspected and audited. Both are requirements when an output feeds an
enforcement decision. A closed API behind a vendor boundary cannot offer either.

Briefs are written in the working language of the authority that will act on them, set by
`output_language` in the regulatory layer. Inspectors should not have to read enforcement
paperwork in a foreign language, and an open model running locally can serve languages a
vendor API may not prioritise. The validator's patterns cover Spanish as well as English
for the same reason.

---

## Sample output

### 1. Deterministic cross-reference

`python src/main.py --cross-reference-only` — verbatim program output:

```
========================================================================
FACTUAL DOSSIER - Gulf of Cadiz (demo) - scene 2026-07-18T06:12:00Z
========================================================================
Detections analysed: 12
AIS carriage threshold applied: 15.0 m (length uncertainty +/-2.0 m)
Active closure: Northern Fishing Ground - seasonal spawning closure (spawning season)
Patrol base: Port of Cadiz patrol base (demo) (radius 120 km)

Classification summary:
  high_priority      3
  medium_priority    4
  no_indicators      3
  ais_not_applicable 2

--- INSPECTION CANDIDATES ---

  D-004  -> HIGH_PRIORITY | 2 independent indicator(s) concur | 40.77 km from base
    Pos 36.47, -6.74 | length 22.0 m | AIS: unmatched (dark) | likely gear: purse_seine
    Zone: Islote Sur Integral Reserve (integral_reserve)
    Indicator: radar-estimated length 22.0 m is above the 15.0 m threshold beyond sensor uncertainty and no AIS broadcast was matched; if this is a Union fishing vessel exceeding 15.0 m LOA, the AIS carriage and operation requirement is potentially concerned (Article 10(1), Council Regulation (EC) No 1224/2009, as amended by Regulation (EU) 2023/2842)
    Indicator: apparent fishing activity inside integral_reserve 'Islote Sur Integral Reserve' where all fishing gear is prohibited (activity per contextual classifier, non-observational)
      +40  no AIS broadcast matched while the carriage requirement is potentially engaged (length firmly above threshold)
      +30  apparent fishing where all gear is prohibited (RES-03)
      +10  contextual classifier indicates likely fishing activity (non-observational) - corroboration only

  D-010  -> HIGH_PRIORITY | 2 independent indicator(s) concur | 38.0 km from base
    Pos 36.44, -6.7 | length 26.5 m | AIS: unmatched (dark) | likely gear: bottom_trawl
    Zone: Islote Sur Integral Reserve (integral_reserve)
    Indicator: radar-estimated length 26.5 m is above the 15.0 m threshold beyond sensor uncertainty and no AIS broadcast was matched; if this is a Union fishing vessel exceeding 15.0 m LOA, the AIS carriage and operation requirement is potentially concerned (Article 10(1), Council Regulation (EC) No 1224/2009, as amended by Regulation (EU) 2023/2842)
    Indicator: apparent fishing activity inside integral_reserve 'Islote Sur Integral Reserve' where all fishing gear is prohibited (activity per contextual classifier, non-observational)
      +40  no AIS broadcast matched while the carriage requirement is potentially engaged (length firmly above threshold)
      +30  apparent fishing where all gear is prohibited (RES-03)
      +10  contextual classifier indicates likely fishing activity (non-observational) - corroboration only

  D-006 [DEMO VESSEL B / ESP]  -> HIGH_PRIORITY | 2 independent indicator(s) concur | 78.21 km from base
    Pos 37.02, -6.92 | length 31.0 m | AIS: matched | likely gear: bottom_trawl
    Zone: Northern Fishing Ground - seasonal spawning closure (seasonal_closure)
    Indicator: gear 'bottom_trawl' (fleet registry) prohibited in seasonal_closure 'Northern Fishing Ground - seasonal spawning closure'
    Indicator: contextual classifier indicates likely fishing activity (non-observational) during active closure (spawning season) in 'Northern Fishing Ground - seasonal spawning closure'
      +30  registry gear prohibited in zone (CLS-02)
      +30  likely fishing during active closure (CLS-02)
      +10  contextual classifier indicates likely fishing activity (non-observational) - corroboration only

  D-001  -> MEDIUM_PRIORITY | 1 independent indicator(s) concur | 71.04 km from base
    Pos 36.72, -7.05 | length 34.0 m | AIS: unmatched (dark) | likely gear: bottom_trawl
    Zone: Bajo de los Corales Marine Protected Area (marine_protected_area)
    Indicator: radar-estimated length 34.0 m is above the 15.0 m threshold beyond sensor uncertainty and no AIS broadcast was matched; if this is a Union fishing vessel exceeding 15.0 m LOA, the AIS carriage and operation requirement is potentially concerned (Article 10(1), Council Regulation (EC) No 1224/2009, as amended by Regulation (EU) 2023/2842)
    Context (not an indicator): radar-inferred gear class 'bottom_trawl' would be prohibited in marine_protected_area 'Bajo de los Corales Marine Protected Area', but gear inference for an unmatched detection is enrichment, not observation - context only, to be verified on inspection
      +40  no AIS broadcast matched while the carriage requirement is potentially engaged (length firmly above threshold)
      +10  contextual classifier indicates likely fishing activity (non-observational) - corroboration only

  D-002  -> MEDIUM_PRIORITY | 1 independent indicator(s) concur | 68.15 km from base
    Pos 36.71, -7.02 | length 28.5 m | AIS: unmatched (dark) | likely gear: bottom_trawl
    Zone: Bajo de los Corales Marine Protected Area (marine_protected_area)
    Indicator: radar-estimated length 28.5 m is above the 15.0 m threshold beyond sensor uncertainty and no AIS broadcast was matched; if this is a Union fishing vessel exceeding 15.0 m LOA, the AIS carriage and operation requirement is potentially concerned (Article 10(1), Council Regulation (EC) No 1224/2009, as amended by Regulation (EU) 2023/2842)
    Context (not an indicator): radar-inferred gear class 'bottom_trawl' would be prohibited in marine_protected_area 'Bajo de los Corales Marine Protected Area', but gear inference for an unmatched detection is enrichment, not observation - context only, to be verified on inspection
      +40  no AIS broadcast matched while the carriage requirement is potentially engaged (length firmly above threshold)
      +10  contextual classifier indicates likely fishing activity (non-observational) - corroboration only

  D-008  -> MEDIUM_PRIORITY | 1 independent indicator(s) concur | 102.56 km from base
    Pos 36.3, -7.4 | length 55.0 m | AIS: unmatched (dark) | likely gear: bottom_trawl
    Indicator: radar-estimated length 55.0 m is above the 15.0 m threshold beyond sensor uncertainty and no AIS broadcast was matched; if this is a Union fishing vessel exceeding 15.0 m LOA, the AIS carriage and operation requirement is potentially concerned (Article 10(1), Council Regulation (EC) No 1224/2009, as amended by Regulation (EU) 2023/2842)
      +40  no AIS broadcast matched while the carriage requirement is potentially engaged (length firmly above threshold)
      +10  contextual classifier indicates likely fishing activity (non-observational) - corroboration only

  D-005  -> MEDIUM_PRIORITY | 1 independent indicator(s) concur | 44.02 km from base
    Pos 36.49, -6.78 | length 9.5 m | AIS: unmatched (dark) | likely gear: small_scale
    Zone: Islote Sur Integral Reserve (integral_reserve)
    Indicator: apparent fishing activity inside integral_reserve 'Islote Sur Integral Reserve' where all fishing gear is prohibited (activity per contextual classifier, non-observational)
    AIS note: Below the AIS carriage threshold: absence of an AIS broadcast is not an indicator. Other indicators, if any, remain.
      +30  apparent fishing where all gear is prohibited (RES-03)
      +10  contextual classifier indicates likely fishing activity (non-observational) - corroboration only

--- PATROL SEQUENCE (priority, then distance from base) ---
  D-010  high_priority      38.0 km  (36.44, -6.7)
  D-004  high_priority     40.77 km  (36.47, -6.74)
  D-006  high_priority     78.21 km  (37.02, -6.92)
  D-005  medium_priority   44.02 km  (36.49, -6.78)
  D-002  medium_priority   68.15 km  (36.71, -7.02)
  D-001  medium_priority   71.04 km  (36.72, -7.05)
  D-008  medium_priority  102.56 km  (36.3, -7.4)

--- AIS INDICATOR SUPPRESSED (duty of caution) ---
  D-005 (medium_priority): Below the AIS carriage threshold: absence of an AIS broadcast is not an indicator. Other indicators, if any, remain.
  D-007 (ais_not_applicable): Below the AIS carriage threshold: absence of an AIS broadcast is not an indicator. Other indicators, if any, remain. The appropriate cross-check is VMS: vessels of 12.0 m and over must carry an operational VMS (since January 2026), and the authority already holds that track.
  D-011 (ais_not_applicable): Below the AIS carriage threshold: absence of an AIS broadcast is not an indicator. Other indicators, if any, remain.
```

Read D-005 closely, because it is the whole design in one record: a 9.5 m dark vessel.
Its AIS indicator is suppressed — below the threshold, not broadcasting breaches nothing —
but it is apparently fishing inside an integral reserve, so it is a **medium-priority
candidate on the zone indicator alone**, with the suppression stated in the record.
D-007 and D-011 are equally small and equally dark but have no zone violation: they score
zero and are never prioritised. And D-008 is in open water, outside every protected zone,
yet the provision it may breach is named — conditionally, because its flag is unknown.
Neither over-reporting nor under-reporting.

### 2. Analyst agent

`python src/main.py` — representative output (agent wording varies between runs; the
deterministic figures it may cite come from the dossier above, and its output is
validated in code before it is shown):

```
AIS not applicable (indicator suppressed):
  - D-005: below the 15 m carriage threshold, darkness is not an indicator;
           prioritised solely on the integral reserve zone indicator
  - D-007, D-011: below the carriage threshold with no zone violation; excluded

Observed pattern: The three high-priority candidates concentrate in two regulated
areas: the Islote Sur Integral Reserve (D-004, D-010) and the active seasonal
closure CLS-02 (D-006, AIS-matched). Two dark medium-priority vessels (D-001,
D-002) sit inside MPA-01, while D-008 is dark in open water.

Stated limitations:
  - The fishing-activity signal is a contextual classifier, not observed
    behaviour; gear inference for unmatched detections is enrichment.
  - A lawful AIS switch-off under Article 10(2) cannot be ruled out for dark
    vessels; whether a notification was filed must be checked.
  - Flag state of unmatched detections is unknown, so the carriage requirement
    can only be conditionally engaged.
  - This is a single radar snapshot; no temporal persistence is available.
```

The analyst's output is then checked in code (`validate_prioritisation`): ids that are
not inspection candidates, ids that do not exist, or a silently-suppressed vessel
reintroduced into the narrative all **block the run** before the writer ever starts.

### 3. Writer agent — inspection briefs

Representative output (same caveat as above; structure and guarantees are enforced by
`validate.py`):

```
  [HIGH] D-010 - 36.44, -6.7
    - no AIS broadcast matched, length firmly above the carriage threshold
    - apparent fishing activity inside an integral reserve where all gear is
      prohibited
    Regulation: if this is a Union fishing vessel exceeding 15 m LOA,
                Article 10(1), Council Regulation (EC) No 1224/2009, as amended
                by Regulation (EU) 2023/2842; all-gear prohibition of the
                Islote Sur Integral Reserve
    Action:     Board and verify gear and licence; 38 km from base, first stop
                of the patrol sequence.
    Caveat:     Check whether an AIS switch-off notification was filed for this
                time window (Art. 10(2)): the master may lawfully switch off
                AIS where crew safety or security is imminently at risk.

  [MEDIUM] D-005 - 36.49, -6.78
    - apparent fishing activity inside an integral reserve where all gear is
      prohibited
    Regulation: all-gear prohibition of the Islote Sur Integral Reserve
    Action:     Visual check while transiting to D-010; 44 km from base.
    Caveat:     Below the AIS carriage threshold: absence of a broadcast is not
                an indicator here, and radar-based activity inference for a
                9.5 m vessel may be wrong.

========================================================================
OUTPUT VALIDATION
========================================================================
Output validation: no issues.
```

D-006 is broadcasting, so its brief (not shown) cites only the closure and the gear
prohibition — never the carriage requirement — and its caveat says nothing about AIS.
D-005's brief exists because its zone indicator is real, but no AIS provision appears in
it. These properties are enforced in code, not hoped for.

**Validation gates the output.** Every report is checked against the dossier before a
human sees it. If any blocking issue is found — an AIS citation against a broadcasting or
sub-threshold vessel, an altered coordinate, a regulation named for a record with no
indicators, a high-priority record silently missing its brief, or a suppressed vessel
reintroduced into the narrative — **the briefs are withheld, only the issue summary is
printed, and the process exits non-zero**. Positions in briefs are compared numerically
against the dossier: the model formats coordinates, it never sources them. Both agents
are validated, in both languages the system currently ships prompts for (English and
Spanish patterns).

---

## Model selection

We ran the identical pipeline across the Nemotron 3 family rather than assuming the
largest model is the right one.

| Model | Behaviour observed |
|---|---|
| `nemotron-3-nano-30b-a3b` | Fast. In early runs it reintroduced suppressed sub-threshold vessels into its narrative and drifted towards invented caveats. **Those failure modes are exactly what the validator now blocks deterministically** — with the guardrail in code, nano is a viable choice where latency or cost dominates, because a bad output cannot reach an inspector. |
| `nemotron-3-super-120b-a12b` | Holds the caution boundary throughout without tripping the validator: fewer blocked-and-retried runs. Caveats stay conservative and grounded. **Current default.** |
| `nemotron-3-ultra-550b-a55b` | Largest; evaluated for the final demo where latency is not a constraint. |

The point is not "the big model is safe and the small one is not" — safety is not
delegated to model choice at all. The deterministic validator makes the safety properties
hold for **any** model; model choice then becomes what it should be: a quality/latency
trade-off, measured by how often a model's output survives validation unblocked.

Each agent can run on a different model via `ANALYST_MODEL` and `WRITER_MODEL`, so
reasoning-heavy and formatting-heavy steps can be sized independently.

**Observed failure mode.** When the Article 10 carriage requirement was first surfaced to
the writer agent, the model began stamping it onto AIS-matched vessels that were plainly
broadcasting, and generalised a zone's specific gear restrictions into a blanket
prohibition. Attributing a breach to a compliant vessel is the worst error this system can
make, so the writer is constrained to cite only provisions present in that record's own
indicator list, and the validator independently blocks any AIS citation for a record
whose indicators do not engage it. Guardrails here are not prompt hygiene; they are the
product.

---

## Current status

Working end-to-end prototype: deterministic engine plus both agents running against open
Nemotron models. Demo data is synthetic; its schema mirrors the real sources, so going
live starts with reimplementing `src/data.py` — with one honest caveat. The real Global
Fishing Watch SAR dataset provides, per detection: position, timestamp, estimated length,
whether the detection was matched to an AIS broadcast, and a **contextual**
fishing-likelihood score. It does **not** provide `likely_gear` or `speed_kn` for
unmatched detections — in our demo data those are enrichment. The engine already treats
them accordingly (gear inference for unmatched detections is context, not an indicator;
the fishing score is labelled non-observational), so no scoring logic changes when the
enrichment fields are absent, but a live deployment must either drop them or source them
from the fleet registry for matched vessels.

| Layer | Planned source |
|---|---|
| Vessel detections | Global Fishing Watch — "Vessel detections from Sentinel-1 SAR" |
| Benchmark / training | xView3 dark vessel detection dataset |
| Raw imagery (phase 2) | Copernicus Data Space Ecosystem (Sentinel-1 / Sentinel-2) |
| Protected areas | Natura 2000 marine, WDPA, marine reserves of fishing interest |
| Seasonal closures | Official bulletins |

### Known limitations (deliberate, documented)

- `length_sigma_m` (radar length uncertainty) is a placeholder pending calibration
  against Paolo et al. 2024.
- Scoring weights are transparent but not calibrated against enforcement outcomes;
  calibration is phase 3.
- The exact paragraph numbering of the amended Article 10 should be confirmed against
  the consolidated text of Regulation (EC) No 1224/2009 as amended by Regulation (EU)
  2023/2842.
- Zone polygons are demo rectangles with a dependency-free point-in-polygon test; real
  Natura 2000 / WDPA geometries need shapely + geopandas.

### Roadmap

- **Phase 1 (done):** deterministic cross-reference + two-agent pipeline on existing
  detections, both agent outputs validated in code.
- **Phase 2 (hackathon):** real Global Fishing Watch data; multimodal reasoning over
  Sentinel-1 image chips using `nemotron-3-nano-omni-30b-a3b-reasoning`; self-hosted NIM
  deployment on OCI so that operational data stays inside the authority's environment.
- **Phase 3:** evaluation harness measuring precision against known enforcement outcomes;
  weight calibration; domain fine-tuning with LoRA.

---

## Quick start

```bash
# 1. Deterministic engine only — no dependencies, no API key
python src/main.py --cross-reference-only

# 2. Full pipeline
pip install -r requirements.txt
export NVIDIA_API_KEY='nvapi-...'        # Windows: $env:NVIDIA_API_KEY = 'nvapi-...'
python src/main.py

# 3. Try a different model
export NEMOTRON_MODEL='nvidia/nemotron-3-nano-30b-a3b'

# 4. Safety tests: duty of caution, scoring invariant, error policy, validator
python src/test_caution.py
```

Get an API key at [build.nvidia.com](https://build.nvidia.com). One key works for every
model — the model is chosen per request, not per key.

`python src/list_models.py nemotron` lists the models available to your key.

---

## Repository layout

```
src/data.py          data loading — the first file that changes to go live
src/geo.py           point-in-polygon and distance, dependency-free
src/analysis.py      deterministic cross-reference — the agents' tool
src/validate.py      checks BOTH agents' output against the dossier; blockers stop the report
src/agents.py        Nemotron agents: analyst + writer
src/main.py          orchestrator — validation gates every model output
src/test_caution.py  safety tests: caution, scoring invariant, error policy, validator
src/list_models.py   helper: list models available to your API key
demo_data/           synthetic demo data (regulatory layer is configuration, not code)
```

---

## Target users

The European Fisheries Control Agency (headquartered in Vigo, Spain) and national and
regional fisheries inspection services.

---

## Team

Four undergraduate students (Spain).

- Jorge Rodríguez Fernández
- Shengyu Chen
- Pablo Vergés
- Arsenii Samokhin

The commit history was produced from a single shared machine during the codefest and
does not reflect individual authorship; design, engine, agents, evaluation and
documentation were joint work by the four members listed above.

## License

MIT — see `LICENSE`.

## Data and model licensing

All planned data sources are open public data. Model weights are open and used under their
respective licenses; see the model card on build.nvidia.com.

## Attribution

Vessel detection data provided by Global Fishing Watch (globalfishingwatch.org).
