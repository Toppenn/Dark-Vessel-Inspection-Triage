# Dark Vessel Inspection Triage

**NVIDIA Open Models Codefest 2026 — team submission**

[![checks](https://github.com/Toppenn/Dark-Vessel-Inspection-Triage/actions/workflows/checks.yml/badge.svg)](https://github.com/Toppenn/Dark-Vessel-Inspection-Triage/actions/workflows/checks.yml)

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

1. **Gates the scene** on season, moon and tide before anything else — a
   scanning-priority signal that ranks which nights are worth tasking and never touches a
   vessel score.
2. **Cross-references** every detection against AIS matching, marine protected area
   boundaries, seasonal closures, permitted fishing gear, and a registry of charted fixed
   structures, so a platform is not mistaken for a boat.
3. **Scores** each detection with a fully itemised breakdown — every point awarded has a
   stated reason. No black box.
4. **Sequences** the resulting candidates against a patrol base and a reachable radius,
   because a target that scores highly 200 km away is not the next inspection.
5. **Reasons** over the scene as a whole: ranks candidates, identifies spatial clustering,
   and declares what the analysis cannot know.
6. **Drafts inspection briefs** stating the indicators, the regulation concerned, the
   suggested action, and the innocent explanation that could account for the indicator.
7. **Validates its own output** against the factual dossier, and refuses to issue a report
   that fails.

---

## Duty of caution

**Not broadcasting AIS is not, by itself, evidence of anything.** Getting this right in
both directions is the core of the system.

### The threshold suppresses one indicator, not the vessel

Vessels below the legal length threshold are not required to broadcast at all. For those,
the system **suppresses the AIS indicator and its points** — and nothing else. Every other
indicator that vessel may have raised stands, and it can still become an inspection
candidate on that basis.

This distinction matters more than it looks. An earlier version of this system classified
sub-threshold vessels as "non-assessable" and zeroed their entire record. The effect was
that a 9 m vessel apparently fishing inside an integral reserve disappeared from the output
**because it was dark**, while the same vessel doing the same thing with its transponder on
was flagged. That is an incentive to switch the transponder off. In the demo scene, D-005 is
exactly that case: it is below the threshold, its AIS indicator is suppressed and explained,
and it is still a medium-priority candidate because of a zone indicator.

### Presence is not activity

A zone violation requires activity, and the only activity signal available is the
contextual classifier. The fleet registry gear class states what a vessel is *licensed*
for, not what it is doing, so it cannot support a claim that fishing is taking place.

This is not hypothetical caution. An earlier version raised "apparent fishing activity"
against a compliant vessel — AIS on, transiting an integral reserve at 11 knots, activity
classifier at 0.05 — purely because it had a purse seine on its licence. The system was
asserting something the classifier had explicitly not said. That branch is gone, and a
regression test now holds the line in both directions: the compliant transit raises no
indicator, and a vessel actually fishing in the same reserve still does.

### A charted structure is not a dark vessel

A fixed platform returns a bright, persistent radar signature and broadcasts no AIS, which
is exactly the shape of a dark-vessel candidate. Attributing it to a vessel would put a
patrol on a heading toward a lump of steel that has been there for years.

Detections that coincide with a charted structure in the registry are therefore classified
`fixed_structure`, score zero, and raise no candidate. The record names the structure it was
attributed to, and the indicators it *would* have raised are surfaced as context rather than
dropped, so the reader can see what the guard suppressed and disagree with it. An identical
dark vessel away from the structure remains a candidate, and an empty registry leaves
classification untouched — the guard only ever subtracts, and only where the chart says so.

### Season before moon

The environmental gate (`src/environment.py`) ranks which nights are worth tasking for
angula: dark nights around spring tides, in season. It is a *scanning-priority* signal
reported at scene level, never a per-vessel indicator, and a regression test asserts that
swinging its label from `out_of_season` to `high` moves no vessel score at all.

Season comes first, because it is the filter anyone in the sector applies before looking at
the moon. An earlier version modelled the lunar cycle correctly and ignored the campaign, so
a July new moon — months after the fishery closes — was reported as peak conditions. The
window is configuration, not astronomy: each autonomous community opens its own campaign and
the dates move, so it is set per jurisdiction and the shipped default is a placeholder in
exactly the way `length_sigma_m` is one. A window that crosses the year boundary is handled
as such; a naive `start <= today <= end` would exclude December and January, which is most
of the season.

**And the sensor that would see an angula boat is not this one.** Angula is fished with
cedazo from the shore or from small craft inside estuaries, far below Sentinel-1's ~15 m
detection floor, while the detections here are 9-31 m vessels in open water. The gate
prioritises estuary tasking with whatever sensor is appropriate; nothing in it should be
read as implying that an angula boat would appear in a SAR scene. That limit is written into
the module rather than left for the framing to obscure.

### The legal basis, and its limits

The threshold is not arbitrary. Article 10(1) of Council Regulation (EC) No 1224/2009, as
amended by Regulation (EU) 2023/2842, requires Union fishing vessels exceeding 15 m length
overall to carry and maintain an operational AIS. Three consequences are built into the
engine:

- **"Exceeding" means strictly greater.** A vessel of exactly 15.0 m is not covered.
- **The obligation is on *Union* vessels**, and a dark vessel's flag State is unknown by
  definition. The indicator is therefore phrased conditionally — *"if this is a Union
  fishing vessel exceeding 15 m LOA, the carriage requirement is potentially concerned"* —
  and the record carries `jurisdiction: unknown`.
- **Article 10(2) permits a lawful switch-off** where crew safety or security is at
  imminent risk. A dark vessel may be lawfully dark. Under the revised regime the master
  must notify the switch-off, so the brief's caveat points to a check the authority can
  actually perform rather than an untestable excuse.

Below the threshold the correct statement is not "unobservable" but "the appropriate
cross-check is VMS": vessels of 12 m and over must carry an operational VMS, a track the
authority already holds.

*The precise paragraph numbering should be confirmed against the consolidated text before
operational use.*

### The measurement is estimated, and the threshold sits on the sensor floor

`estimated_length_m` is inferred from radar backscatter, not measured, and the 15 m legal
threshold sits close to the detection floor of Sentinel-1 SAR. In that band the estimation
error is comparable to the distance to the threshold, so a firm/inconclusive/not-applicable
three-state rule applies, governed by a configurable `length_sigma_m`. **The sigma currently
in the configuration is a placeholder**; calibrating it against the published detection
literature is an immediate task, not a finished one.


**A degraded indicator may corroborate a candidacy; it may not create one.** When the
estimate does not clear the threshold once its own uncertainty is applied, the resulting
indicator says so in its own text — and a record carrying only that is recorded, not
actioned. Without the rule, a 14 m estimate against a 15 m threshold with ±2 m of sensor
error would put a vessel on the patrol route on the strength of an indicator reading
"inconclusive", and would create a cliff between 13 m and 14 m on a measurement that cannot
resolve the difference. This is a consequence we introduced ourselves when classification
moved from points to indicator counts: the score distinguished firm from degraded, and the
new classifier initially did not.

These properties are tested, not merely documented — see `src/test_caution.py`.

---

## Architecture

```
scene timestamp ────────────> environmental gate ──> scanning priority (scene level)
                              environment.py         never touches a vessel score

GFW / Sentinel-1 detections ─┐
Marine protected areas       │
Seasonal closures            ├─> deterministic ──> analyst ──> writer ──> validator ──> briefs
Gear restrictions            │   cross-reference   (Nemotron)  (Nemotron)  validate.py
Charted fixed structures     │   analysis.py
Patrol base                 ─┘   auditable, no LLM                         auditable, no LLM
```

**Positions, geometry and scores are computed deterministically and are never generated by
the model** — and that claim is enforced, not asserted: the validator compares every
position in a brief against the dossier. In an enforcement file the figures must be
reproducible and auditable. The open models do what they are genuinely good at: interpreting
context, prioritising, and writing for a human reader.

**Why open models matter here.** Because the weights are open, the system can be deployed
inside the authority's own environment — operational data never leaves it — and its
reasoning can be inspected and audited. Both are requirements when an output feeds an
enforcement decision. A closed API behind a vendor boundary offers neither.

Briefs are written in the working language of the authority that will act on them, set by
`output_language`. Inspectors should not have to read enforcement paperwork in a foreign
language, and an open model running locally can serve languages a vendor API may not
prioritise. The validator's guardrail patterns are multilingual for the same reason.

---

## Output validation

Prompting does not guarantee the guarantees. Models follow instructions approximately, and
here an approximate answer can attach a breach to a compliant vessel. So the model's output
is checked against the factual dossier in code, before a human sees it. **If a blocking
issue is found the briefs are not printed and the process exits non-zero.**

The validator checks, for both the analyst and the writer:

| Check | Severity |
|---|---|
| AIS carriage requirement invoked against a broadcasting vessel — in the regulation, the indicators, or the suggested action | blocker |
| A brief position that does not match the dossier | blocker |
| A high-priority record with no brief (under-reporting) | blocker |
| A vessel with its AIS indicator suppressed and no other indicators, reintroduced in the narrative | blocker |
| A prioritised id that does not exist in the dossier, or is not a candidate | blocker |
| A high-priority record the analyst left out of its prioritisation | blocker |
| An indicator written as a category label ("ais", "zone") rather than a statement | blocker |
| Brief indicators citing none of the record's zone identifiers, figures or legal references | blocker |
| A brief listing more indicators than the record contains (invention by addition) | blocker |
| A regulation field restating the indicators instead of naming the provision | warning |
| A brief stating a priority the engine did not assign (a high written up as low) | blocker |
| A regulation carrying anchors that belong exclusively to a different detection | blocker |
| A brief raising indicators with no caveat at all | blocker |
| A caveat describing a vessel as under the carriage threshold when the record exceeds it | blocker |
| A suggested action invoking seizure or arrest, beyond an inspector's authority | blocker |
| A narrative claim listing a record among a priority class it does not belong to | warning |
| A record with indicators but no regulation named, including an empty field | warning |
| A suggested action that is only context ("40.77 km from base") with no instruction left | warning |
| A medium-priority record with no brief | warning |
| A medium-priority record the analyst left out of its prioritisation | warning |
| An analyst reason citing figures or zones that do not appear in its own record | blocker |

Each rule exists because a model produced that failure in a real run. Position tolerance is
0.001° (~110 m): the model copies a coordinate rather than computing one, so the tolerance
absorbs formatting rounding and nothing else. **Indicator fidelity is bounded in both directions, in every language.** The anchor check
compares tokens that translation leaves untouched — zone identifiers, figures and legal
references — so it runs whatever the authority's working language is. Word overlap remains a
secondary signal, but only where brief and dossier share a language.

Anchors bound *substitution*: a brief that replaces the record's content carries none of
them. They do not bound *addition* — a brief that reproduces every indicator faithfully and
appends an invented one keeps every anchor and passes. Addition is the likelier failure,
because models embellish more readily than they replace, and in an inspection brief an added
line is an accusation nobody observed. So the count is bounded too: a brief may consolidate
two indicators into one well-formed statement, but never list more than the record contains.
Both are blockers, because fabricated text sits in the field an inspector reads first.

Making the zone identifier part of every zone indicator is what made the anchor check
possible in any language, and it makes the indicator more precise for the inspector at the
same time. Anchors also accept either decimal separator, because the engine writes `15.0`
and a Spanish brief writes `15,0`: punctuation convention is not a fidelity failure, and
matching only the dot would have blocked faithful translations.

Two of these rules exist because the guardrail was probed rather than trusted. A brief could
state a priority the engine never assigned — a high-priority record written up as "low",
which is under-reporting delivered in the one field an inspector uses to order the day. And
two briefs could have their regulations swapped and pass everything, because matching on
shared anchors is not enough: the threshold figure appears in every AIS citation, so any two
of them always intersect. What identifies misattribution is an anchor belonging *exclusively*
to another detection.

**Previously known blind spots, now resolved.** In earlier versions, three constructions could pass that a reader would call wrong: a brief with no caveat, a caveat that contradicted its own record, and a suggested action that exceeded the system's remit. These are now strictly blocked by three new deterministic guardrails:

- **Mandatory Context Caveats (Rule A):** a brief that raises indicators must carry a
  caveat. The caveat is not a disclaimer; it is the counter-hypothesis the inspector has to
  rule out, and a brief that offers none is unbalanced by omission.
- **Factual Length Consistency (Rule B):** cross-references the record's length against
  the caveat. A vessel at or above the carriage threshold cannot be described as falling
  below it, because that invites an inspector to dismiss a live indicator. The threshold is
  read from the dossier rather than written into the rule, so it follows a jurisdiction that
  sets its own.
- **Authority Scope Limitation (Rule C):** the system proposes inspection; it does not
  order seizure. An action invoking *seize*, *confiscate*, *arrest* or *impound* — in either
  working language — exceeds what an inspector may do and is blocked.

Two others were closed only after a real run exposed them: the analyst stated a length of 19 m for a 55 m
vessel and passed clean, because nothing compared its prose against the record; and anchors
were being lost to non-breaking hyphens, since the model writes `RES‑03` as readily as
`RES-03`. Both are now normalised and checked. The engine itself is unaffected: 20,000
randomised detections against the declared invariants produce no violation.

---

## Sample output

`python src/main.py --cross-reference-only` — no API key, no network:

```
Detections analysed: 13
AIS carriage threshold applied: 15.0 m (length uncertainty +/-2.0 m)
Environmental context (waxing crescent): angula suitability OUT_OF_SEASON
  outside the angula campaign window (10-10 to 03-31): the fishery is closed, so
  lunar conditions do not raise scanning priority. Moon figures reported as computed.

Classification summary:
  high_priority      3     medium_priority    4     fixed_structure    1
  no_indicators      3     ais_not_applicable 2

  D-004  -> HIGH_PRIORITY | 2 independent indicator(s) concur | 40.77 km from base
    Indicator: radar-estimated length 22.0 m is above the 15.0 m threshold beyond
      sensor uncertainty and no AIS broadcast was matched; if this is a Union fishing
      vessel exceeding 15.0 m LOA, the AIS carriage and operation requirement is
      potentially concerned (Article 10(1), Council Regulation (EC) No 1224/2009,
      as amended by Regulation (EU) 2023/2842)
    Indicator: presence with a contextual fishing indication inside integral_reserve
      'Islote Sur Integral Reserve' (RES-03) where all fishing gear is prohibited

  D-005  -> MEDIUM_PRIORITY | 1 independent indicator(s) concur | 44.02 km from base
    Pos 36.49, -6.78 | length 9.5 m | AIS: unmatched (dark)
    Indicator: presence with a contextual fishing indication inside integral_reserve
      'Islote Sur Integral Reserve' (RES-03) where all fishing gear is prohibited
    AIS note: Below the AIS carriage threshold: absence of an AIS broadcast is not an
      indicator. Other indicators, if any, remain.

  D-013 -> FIX-01 (fixed_platform): the radar return is attributable to charted
    infrastructure, so no dark-vessel candidate is raised.
```

**D-005 is the case the system exists for.** At 9.5 m it is below the carriage threshold, so
its AIS indicator is suppressed and the suppression is stated — but it is still a candidate,
because it is apparently fishing inside a reserve where all gear is prohibited. The duty of
caution removes one piece of evidence, not the vessel. **D-013** is a charted platform, not a
boat. **D-004** carries two independent indicators, which is what makes it high priority: the
classification counts concurring indicators rather than summing weights.

Full output of all three stages — deterministic engine, analyst agent, writer agent and
validation — is in [docs/SAMPLE_OUTPUT.md](docs/SAMPLE_OUTPUT.md).

---


## Model selection

We ran the identical pipeline across the Nemotron 3 family rather than assuming the largest
model is the right one.

| Model | Behaviour observed |
|---|---|
| `nemotron-3-nano-30b-a3b` | **Failed to complete the writer task.** On the full dossier it collapsed into a degenerate repetition loop, emitting 49 KB of a single repeated sentence without ever opening an object. This is a capability limit, not a formatting one, and no retry recovers it. The agent layer now detects the loop and says so explicitly. |
| `nemotron-3-super-120b-a12b` | Completes both agent roles reliably, keeps the suppression rule intact in its narrative, and restates indicator text faithfully. **Current default.** |
| `nemotron-3-ultra-550b-a55b` | Largest; evaluated for the final demo where latency is not a constraint. |

Each agent can run on a different model via `ANALYST_MODEL` and `WRITER_MODEL`, so
reasoning-heavy and formatting-heavy steps can be sized independently.

**Observed failure modes, and what we did about them.** In one run the writer copied the
analyst's shorthand category labels into the briefs, so an inspector would have received
"ais" and "zone" instead of the facts. In another it omitted a medium-priority record
entirely, and stamped the AIS carriage requirement onto vessels that were plainly
broadcasting. We did not respond by writing a longer prompt: each of those failures is now a
deterministic rule in `validate.py` with a test that reproduces it. **Guardrails here are not
prompt hygiene; they are the product.**

**A guardrail that rejects real data is worse than the fabrication it catches.** The check on
the analyst's prose compared its figures against the record's indicators and length only —
so when the analyst correctly wrote "44.02 km from base", quoting a distance the dossier
itself computes, four reports were blocked outright. The comparison now covers every figure
the dossier legitimately holds for a record: length, distance, position, score, and its zone
identifiers. The fabricated-length case it was written for is still caught.

**Asking again beats warning about it.** The analyst's recurring failure is truncation, not
invention: it ranks the obvious candidates and stops, dropping one to three medium-priority
records. The validator reports that, but a warning on a report nobody re-runs is worse than
asking again — so `prioritise` retries once with the dropped ids fed back, the same shape
`_complete_json` already uses for a malformed response. The retry is kept only if it covers
more ground than the first answer, so a second truncation cannot replace a better one. The
prompt also states the candidate count and that ranking is not selection: a low rank says a
record comes later, while omission says nothing about it at all.

**The validator has been wrong three times, and each is now a regression test.** Two rules
once passed a report that was visibly flawed: an empty `regulation` field slipped through a
check that looked only for the words "none identified", and a misattributed priority claim
written without parentheses slipped through a pattern that required them. The third failed
the other way — it flagged all seven briefs in a correct report, because it matched any
action *starting* with a distance, and the model had written "38.0 km from base: board and
verify gear", a perfectly actionable line with the range in front. The rule now asks whether
an instruction remains once the distance is set aside. A guardrail that has never been
checked against both a failure it should catch and a legitimate case it should not is an
assumption, not a guarantee.



**Classification counts indicators; it does not total points.** Two or more independent
indicators concurring makes a record high priority, one makes it medium, none makes it
neither. The weights survive only to order records *within* a class.

That change came out of a bug. A corroboration item was awarding points for the activity
classifier even where an indicator already rested on it — one observation counted twice —
and removing the double count moved a record across the high-priority boundary. A threshold
that shifts when a double count is removed was measuring the double count. Counting
concurring indicators is also the claim the output already makes to its reader, so the
number shown and the classification given are now the same fact.

The weights remain uncalibrated against enforcement outcomes and are never presented as a
probability of infringement. The engine enforces the invariant that a record scores above
zero if and only if it has at least one indicator.

**An open question we have not resolved.** Radar-inferred *gear* is treated as context and
scores nothing, because it is an inference rather than an observation. Radar-inferred
*length* near the threshold does produce an indicator that cites a legal provision. Both
come from the same sensor. There is an argument for the asymmetry — length is a continuous
quantity with a bounded, quantifiable uncertainty, while gear is a categorical guess with
no equivalent band — but we would rather flag it as unresolved than defend it as settled.

---

## Current status

Working end-to-end prototype: deterministic engine, two agents on open Nemotron models, and
a deterministic validator, with 79 checks that run without an API key or network access.
76 of them need no dependencies at all; the remaining three exercise the analyst-omission
helper and so require the OpenAI SDK.
`pyright` reports zero errors across `src/` and `scaffolding/`. Demo data is synthetic.

**What the real source does and does not provide.** Global Fishing Watch publishes, per SAR
detection, an estimated length, AIS matching status and model scores. It does not publish
gear type, speed or heading for unmatched detections, and it cannot: a Sentinel-1 scene is an
instant, not a trajectory. Its fishing classification for unmatched detections is contextual
rather than observational. The engine reflects this — gear is context rather than an
indicator for dark targets, and the fishing item is labelled non-observational — so going
live means replacing `src/data.py` **and** dropping the fields the demo enriches.

| Layer | Planned source |
|---|---|
| Vessel detections | Global Fishing Watch — "Vessel detections from Sentinel-1 SAR" (access granted) |
| Benchmark | xView3 dark vessel detection dataset |
| Raw imagery (phase 2) | Copernicus Data Space Ecosystem (Sentinel-1) |
| Protected areas | Natura 2000 marine, WDPA, marine reserves of fishing interest |
| Seasonal closures | Official bulletins |
| Charted fixed structures | National hydrographic charts / offshore infrastructure registries |
| Angula campaign window | The order published by the relevant autonomous community |

### Roadmap
- **Phase 1 (done):** deterministic cross-reference, two-agent pipeline, output validator,
  patrol sequencing, the fixed-infrastructure guard, and the environmental gate
  (`src/environment.py`) — season, moon phase and spring/neap tendency as a
  *scanning-priority* signal that never touches a vessel score. High-water timing is left as
  a real-data plug-in point, not faked.
- **Phase 2 (in progress):** a SAR vessel detector (`scaffolding/vision.py`) — CA-CFAR with a
  Lee speckle filter, numpy-only, deterministic and auditable. It turns a Sentinel-1
  intensity chip into detections (position, coarse length, confidence) that feed the
  AIS-matching stage. A fine-tuned CNN served via TensorRT/NIM slots into the same
  `detect_vessels` seam once weights exist — there is no fake YOLO standing in for it. Still
  ahead: real Global Fishing Watch data; real Natura 2000 polygons via shapely (the
  dependency-free ray casting cannot handle holes and multipolygons); multimodal chip
  reasoning with `nemotron-3-nano-omni-30b-a3b-reasoning`; self-hosted NIM on OCI so
  operational data stays inside the authority's environment.
- **Phase 3:** calibrate the length-uncertainty sigma against the detection literature and
  the angula season window against the campaign published for the jurisdiction; an evaluation
  harness measuring precision against known enforcement outcomes; recurring closures that
  cross a calendar year; domain fine-tuning with LoRA.

`docs/CLOSING_REPORT.md` carries the phase-by-phase status, the verification table and the
deliberate ceilings — what does not run here, and why it is not pretended to.

---

## Quick start

```bash
# 1. Deterministic engine only — no dependencies, no API key
python src/test_caution.py     # 76 of 79 checks; the rest need the SDK
python src/eval_agent.py       # red-team harness, no dependencies
python src/main.py --cross-reference-only

# 2. Full pipeline
pip install -r requirements.txt
export NVIDIA_API_KEY='nvapi-...'        # Windows: $env:NVIDIA_API_KEY = 'nvapi-...'
python src/main.py

# 3. Choose models per agent
export ANALYST_MODEL='nvidia/nemotron-3-super-120b-a12b'
export WRITER_MODEL='nvidia/nemotron-3-super-120b-a12b'

# 4. Checks — no API key, no network
python src/test_caution.py     # 79 checks: caution, invariants, validator rules
python src/eval_agent.py       # red-teams the guardrail with real LLM failure modes
python src/environment.py      # season gate, year-crossing window, error policy

# 5. Live Global Fishing Watch SAR detections (falls back to demo without a token)
export GFW_TOKEN='...'                    # from globalfishingwatch.org/our-apis
python src/main.py --source gfw

# --- scaffolding: built and self-checking, outside the demo path ---

python scaffolding/vision.py              # CA-CFAR on a synthetic Sentinel-1 chip
python scaffolding/latency.py             # where the time goes; --model-repeat N to bill
streamlit run scaffolding/app.py          # officer triage view (needs streamlit)

# Phase 1.2 / 2.1: curation and the training scaffold. Data prep runs on CPU;
# --train needs a GPU and requirements-train.txt.
python scaffolding/curation.py --synthetic 8 --out datasets/sar_vessels
python scaffolding/train_detector.py --data datasets/sar_vessels --dry-run
```

Get an API key at [build.nvidia.com](https://build.nvidia.com). One key works for every
model — the model is chosen per request, not per key.
`python src/list_models.py nemotron` lists the models available to your key.

---

## Repository layout

```
src/                 the engine and the demo path
  analysis.py        deterministic cross-reference — the agents' tool
  validate.py        checks model output against the dossier; blocks on failure
  agents.py          Nemotron agents: analyst + writer
  environment.py     environmental gate (season/moon/tide) — scanning priority
  geo.py             point-in-polygon and distance; shapely optional for GeoJSON
  data.py            data loading — the boundary that changes to go live
  main.py            orchestrator
  test_caution.py    79 checks: duty of caution, invariants, validator rules
  eval_agent.py      Phase 4.1 red-team harness: guardrail catch rate
  validate_structure.py  structural check on the analyst response, before the factual ones
  list_models.py     helper: list the models available to your API key

scaffolding/         built, self-checking, NOT exercised by the demo path
  vision.py          SAR vessel detector (CA-CFAR) — the Step-3 detector
  curation.py        Phase 1.2: CFAR auto-candidate YOLO labels for human review
  train_detector.py  Phase 2.1: validate/split/data.yaml, TensorRT export seam
  latency.py         Phase 4.2: per-stage latency breakdown
  app.py             Phase 5.1: Streamlit triage view for an officer
  README.md          what is here, why it is separate, how to run it

demo_data/           synthetic demo data, schema mirroring the real sources
docs/SAMPLE_OUTPUT.md    full unedited output of all three stages of the demo path
docs/PROMPTS.md      the analyst and writer prompts, rule by rule, and what backs each
docs/CLOSING_REPORT.md   phase-by-phase status, verification table, deliberate ceilings
docs/DEPLOY_NIM_OCI.md   running a self-hosted Nemotron NIM on an OCI GPU shape
pyrightconfig.json   type-check config; optional deps declared, tree stays clean
```

`src/` and `scaffolding/` are separated so the demo path is visible in the tree rather than
asserted in a document: nothing in `src/` imports anything from `scaffolding/`. Both are
type-checked, and `pyright` reports zero errors across the two.

---

## Target users

The European Fisheries Control Agency (headquartered in Vigo, Spain) and national and
regional fisheries inspection services.

---

## Team

Four undergraduate students in Spain. Work was divided across agent orchestration,
geospatial and regulatory data, model serving, and product and evaluation; commits were
made from a shared setup, so the git history does not map one-to-one onto contributors.

- Jorge Rodríguez Fernández
- Shengyu Chen
- Pablo Vergés
- Arsenii Samokhin

## License

MIT — see `LICENSE`.

## Data and model licensing

All planned data sources are open public data. Model weights are open and used under their
respective licenses; see the model card on build.nvidia.com.

## Attribution

Vessel detection data provided by Global Fishing Watch (globalfishingwatch.org).