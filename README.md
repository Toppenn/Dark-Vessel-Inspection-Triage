# Dark Vessel Inspection Triage

**Decision support for fisheries inspection, on open models.**

**NVIDIA Open Models Codefest 2026 — team submission**

[![checks](https://github.com/Toppenn/Dark-Vessel-Inspection-Triage/actions/workflows/checks.yml/badge.svg)](https://github.com/Toppenn/Dark-Vessel-Inspection-Triage/actions/workflows/checks.yml)

An agentic decision-support system that turns open satellite radar detections into
prioritised, explainable inspection briefs for European fisheries control authorities —
with every figure computed by deterministic code, the prose written by open models, and a
validator that withholds the report when the writing does not match the facts.

---

## The problem

Illegal, unreported and unregulated (IUU) fishing is a significant EU policy problem, and
Spain operates one of the largest fishing fleets in the Union. Fishing vessels carry AIS
transponders that broadcast their position — but a transponder can be switched off.
Research using Copernicus Sentinel-1 radar has found that a large share of fishing vessels
at sea are not broadcasting their positions, and that non-broadcasting vessels are more
frequently associated with illicit activity than those that do broadcast.

Detecting them is largely solved. The real problem is elsewhere, and it has two halves.

**A patrol vessel cannot cover an ocean.** One radar scene can return dozens of detections
and there are resources to inspect a few. The operational question is not who is guilty —
it is **where should the next inspection go**.

**And a dark vessel is not necessarily an offender.** Below 15 metres there is no
obligation to broadcast at all, and even above it, Article 10(2) of Council Regulation (EC)
No 1224/2009 permits a master to switch the AIS off where the safety of the crew is at
imminent risk.

Attaching a breach to a vessel that is complying is the worst failure a system like this
can have. But failing to flag one that is not complying is not a lesser failure: it is the
same failure in the other direction.

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

## Where this sits, and what it does not claim

**Stated first, so the project is not oversold.** The data fusion this system sits on top
of already exists and is deployed:

- The **EFCA–EMSA** interagency service has over 500 registered fisheries control users and
  correlates VMS, terrestrial and satellite AIS, LRIT, Vessel Detection Service radar
  reports and Copernicus imagery.
- Over a thousand users access **EMSA's Integrated Maritime Services**, with intensive use
  of Automated Behaviour Monitoring algorithms. Risk-based control planning is already a
  requirement of the Control Regulation, not an innovation.
- **Commercial fisheries monitoring centre software** correlating SAR detections against
  VMS tracks is deployed and on the market.
- **Global Fishing Watch** publishes Sentinel-1 vessel detections labelled as matched or
  unmatched to AIS. It is the source the live data path is written against.
- Nationally, Spain's **fisheries monitoring centre** operates around the clock on the SIPE
  systems.

**This project is not** a detector, not a fusion platform, and not a risk engine competing
with any of the above.

**What it adds** sits downstream of all of it: a **written, checkable justification for each
targeting decision**. An algorithm raises an alert; it does not produce the reasoning an
authority needs afterwards — why this vessel and not that one, which provision is at stake,
and what innocent explanation would account for the same observation. Today an analyst
writes that by hand. That is not a productivity problem; it is a requirement of
administrative law.

And the hardest part to copy is not the drafting. It is the duty of caution expressed as
executable rules, including the guarantee about what must **never be omitted**.

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
detection floor, while the detections here are 9–31 m vessels in open water. The gate
prioritises estuary tasking with whatever sensor is appropriate; nothing in it should be
read as implying that an angula boat would appear in a SAR scene.

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
resolve the difference.

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

**Why a language model at all** — including the honest case for a template baseline, and
what would settle it — is set out in [docs/WHY_AN_LLM.md](docs/WHY_AN_LLM.md).

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
| A brief stating a priority the engine did not assign (a high written up as low) | blocker |
| A regulation carrying anchors that belong exclusively to a different detection | blocker |
| A brief raising indicators with no caveat at all | blocker |
| A caveat describing a vessel as under the carriage threshold when the record exceeds it | blocker |
| A suggested action invoking seizure or arrest, beyond an inspector's authority | blocker |
| An analyst reason citing figures or zones that do not appear in its own record | blocker |
| A regulation field restating the indicators instead of naming the provision | warning |
| A narrative claim listing a record among a priority class it does not belong to | warning |
| A record with indicators but no regulation named, including an empty field | warning |
| A suggested action that is only context ("40.77 km from base") with no instruction left | warning |
| A medium-priority record with no brief, or left out of the prioritisation | warning |

Each rule exists because a model produced that failure in a real run. Position tolerance is
0.001° (~110 m): the model copies a coordinate rather than computing one, so the tolerance
absorbs formatting rounding and nothing else.

**Indicator fidelity is bounded in both directions, in every language.** The anchor check
compares tokens that translation leaves untouched — zone identifiers, figures and legal
references — so it runs whatever the authority's working language is.

Anchors bound *substitution*: a brief that replaces the record's content carries none of
them. They do not bound *addition* — a brief that reproduces every indicator faithfully and
appends an invented one keeps every anchor and passes. Addition is the likelier failure,
because models embellish more readily than they replace, and in an inspection brief an added
line is an accusation nobody observed. So the count is bounded too: a brief may consolidate
two indicators into one well-formed statement, but never list more than the record contains.

Two of these rules exist because the guardrail was probed rather than trusted. A brief could
state a priority the engine never assigned — a high-priority record written up as "low",
which is under-reporting delivered in the one field an inspector uses to order the day. And
two briefs could have their regulations swapped and pass everything, because matching on
shared anchors is not enough: the threshold figure appears in every AIS citation, so any two
of them always intersect. What identifies misattribution is an anchor belonging *exclusively*
to another detection.

**The validator has been wrong three times, and each is now a regression test.** Two rules
once passed a report that was visibly flawed: an empty `regulation` field slipped through a
check that looked only for the words "none identified", and a misattributed priority claim
written without parentheses slipped through a pattern that required them. The third failed
the other way — it flagged all seven briefs in a correct report, because it matched any
action *starting* with a distance, and the model had written "38.0 km from base: board and
verify gear", a perfectly actionable line with the range in front. A guardrail that has
never been checked against both a failure it should catch and a legitimate case it should
not is an assumption, not a guarantee.

---

## Evaluation: measuring the checker, not the model

The system's thesis is that the guarantees live in code rather than in the prompt. That
claim is testable directly, and it is tested in two layers.

### Layer 1 — the red team, on one scene

`src/eval_agent.py` synthesises a correct analyst prioritisation and writer report from a
real dossier, mutates each into one concrete LLM failure mode — a hallucinated id, a moved
coordinate, an AIS accusation against a broadcasting vessel, a dropped high-priority target,
a fabricated indicator — and asserts the validator returns the expected severity. It
includes negative controls: legitimate-but-unusual outputs the guardrail must **not** block,
so over-blocking is measured alongside under-blocking. No API key, no network, no cost.

### Layer 2 — the same red team, over hundreds of independently generated worlds

A rule that holds only because of an accident of the demo scene's geometry would pass
layer 1. `finetune/scene_factory.py` samples complete scenes — geography, zone sets, closure
states, gear restrictions, patrol bases, working languages and length distributions — and
`finetune/harness_over_scenes.py` re-runs the entire red team over every one of them.

Most recent run, 200 generated scenes:

| | |
|---|---|
| Scenes exercised | **177** (23 could not host every mutation and are excluded, not counted as passes) |
| Cases on expected severity | **2,374 / 2,374** |
| Guardrail catch rate on adversarial cases | **1,843 / 1,843** |
| Negative controls not blocked | **531 / 531** |

Per failure family, all at 100%: `ais-misattribution` 99/99, `coordinate` 177/177,
`fabrication` 680/680, `hallucination` 177/177, `over-report` 356/356, `under-report`
354/354.

Reproduce in about a minute, with no GPU and no API key:

```bash
python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
python finetune/harness_over_scenes.py --scenes data/scenes.jsonl
```

### What this does and does not show

It shows the guardrail generalises past the scene it was written against. It does **not**
show the guardrail is complete: it catches the failure modes we thought to encode. The
open problem — evaluating agentic output where there is no ground truth, and specifically
catching *addition* rather than *contradiction* — is the hardest item on the roadmap and
the one that most needs outside input.

---

## Sample output

`python src/main.py --cross-reference-only` — no API key, no network:

```
Detections analysed: 13
AIS carriage threshold applied: 15.0 m (length uncertainty +/-2.0 m)
Environmental context (waxing crescent): angula suitability OUT_OF_SEASON
  outside the angula campaign window (10-10 to 03-31): the fishery is closed, so
  lunar conditions do not raise scanning priority.

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
boat. **D-004** carries two independent indicators, which is what makes it high priority.

Full output of all three stages is in [docs/SAMPLE_OUTPUT.md](docs/SAMPLE_OUTPUT.md).

---

## Model selection

We ran the identical pipeline across the Nemotron 3 family rather than assuming the largest
model is the right one. Each agent can run on a different model via `ANALYST_MODEL` and
`WRITER_MODEL`, so reasoning-heavy and formatting-heavy steps can be sized independently.

| Model | Behaviour observed |
|---|---|
| `nvidia/nemotron-nano-3-30b-a3b` | **Failed to complete the writer task.** On the full dossier it collapsed into a degenerate repetition loop, emitting 49 KB of a single repeated sentence without ever opening an object. This is a capability limit, not a formatting one, and no retry recovers it. The agent layer detects the loop and says so explicitly. Closing this gap is the Codefest work below. |
| `nvidia/nemotron-3-super-120b-a12b` | Completes both agent roles reliably, keeps the suppression rule intact in its narrative, and restates indicator text faithfully. **Current default.** |
| `nvidia/nemotron-3-ultra-550b-a55b` | Largest; evaluated for the final demo where latency is not a constraint. |

**Observed failure modes, and what we did about them.** In one run the writer copied the
analyst's shorthand category labels into the briefs, so an inspector would have received
"ais" and "zone" instead of the facts. In another it omitted a medium-priority record
entirely, and stamped the AIS carriage requirement onto vessels that were plainly
broadcasting. We did not respond by writing a longer prompt: each of those failures is now a
deterministic rule in `validate.py` with a test that reproduces it. **Guardrails here are not
prompt hygiene; they are the product.**

**Asking again beats warning about it.** The analyst's recurring failure is truncation, not
invention: it ranks the obvious candidates and stops. So `prioritise` retries once with the
dropped ids fed back, and the retry is kept only if it covers more ground than the first
answer.

**Classification counts indicators; it does not total points.** Two or more independent
indicators concurring makes a record high priority, one makes it medium, none makes it
neither. That change came out of a bug: a corroboration item was awarding points for the
activity classifier even where an indicator already rested on it — one observation counted
twice — and removing the double count moved a record across the high-priority boundary. A
threshold that shifts when a double count is removed was measuring the double count.

**An open question we have not resolved.** Radar-inferred *gear* is treated as context and
scores nothing, because it is an inference rather than an observation. Radar-inferred
*length* near the threshold does produce an indicator that cites a legal provision. Both
come from the same sensor. There is an argument for the asymmetry — length is a continuous
quantity with a bounded, quantifiable uncertainty, while gear is a categorical guess with no
equivalent band — but we would rather flag it as unresolved than defend it as settled.

---

## Codefest work: closing the small-model gap

*Directory: [`finetune/`](finetune/). Full runbook in [finetune/README.md](finetune/README.md).*

The 30B model fails where the 120B model succeeds. That sentence is a problem for the
product, not just for a benchmark: the whole public-sector argument is that the system runs
inside the authority's own environment, and a 120B model is a much harder thing for a
regional inspection service to host than a 30B model with 3.5B active parameters. The goal
is to replace *"we use the large one because the small one fails"* with **"we fixed the
small one"**, and to have a number behind it.

### The pipeline

```
scene_factory.py       facts, sampled deterministically      (CPU, seconds)
   |                   -> src/analysis.py computes the dossier
   v
gen_teacher.py         Super-120B writes briefs;             (CPU, API-bound)
   |                   validate.py accepts or rejects each one
   v
curate.py              dedup, length filter, leak-free split (CPU, seconds)
   |
   v
nano_writer_lora.yaml  LoRA SFT of Nano-30B-A3B              (1 GPU)
   |
   v
eval_live.py           held-out scenes, base vs adapter      (1 GPU or API)
```

### The load-bearing idea: the validator is the data curator

A teacher output enters the training corpus only if the same executable rules that gate a
real report find no issue in it. The failure modes we are trying to remove from the small
model — citing the AIS carriage requirement against a broadcasting vessel, moving a
coordinate, dropping a high-priority record — therefore **cannot be present in its
supervision**, because those are precisely what `validate.py` blocks.

The teacher's rejection rate is a result in itself: a measurement of the problem the
guardrail exists to solve, taken on real model output rather than on mutations.

### Where synthetic data is used, and where it is deliberately not

The training *inputs* are dossiers, and a dossier is ground truth by construction: every
figure in it was computed by `src/analysis.py`. If a language model invented the dossier,
the supervision signal would inherit the model's errors and the project's governing rule —
*facts are computed, models interpret* — would be false at training time as well as at
inference time.

So the facts are sampled deterministically by `scene_factory.py`, from named case templates
chosen so that the edges the duty of caution lives on are guaranteed to appear: vessels at
exactly 15.0 m, vessels in the inconclusive band, sub-threshold vessels inside reserves,
broadcasting vessels with prohibited gear in an active closure, detections coinciding with
charted structures.

[NeMo Data Designer](https://github.com/NVIDIA-NeMo/DataDesigner) is used for the
**surface** only — place names, designations, closure reasons, port names, working language
— everything that must vary so the model learns the structure of an indicator rather than
the string "Islote Sur", and nothing that must not.
[NeMo Curator](https://github.com/NVIDIA-NeMo/Curator) was evaluated and its dedup stages
map cleanly onto what `curate.py` does; the reasoning for implementing them in the standard
library at this corpus size is in [finetune/CURATOR.md](finetune/CURATOR.md).

### Training

[NeMo AutoModel](https://github.com/NVIDIA-NeMo/Automodel) LoRA SFT, following NVIDIA's own
recipe for this model. Two details are not optional:

- `exclude_modules: ["*.out_proj"]` — the Mamba-2 layers of the hybrid architecture consume
  `out_proj.weight` inside a custom kernel where LoRA cannot apply.
- `mask_generation_prompt: true` — Nemotron's chat template injects an empty reasoning block
  into every assistant turn without `reasoning_content`. Training with loss on that block
  teaches the model to open its reasoning and immediately close it, and the failure being
  fixed *is* a degenerate reasoning loop.

### Reported honestly

This is distillation, and it is labelled as such: the small model is taught to imitate a
large model's validated output on synthetic scenes. It is not evidence that the small model
reasons better, and it says nothing about real Global Fishing Watch data.

The corpus is filtered by the validator and the evaluation uses the same validator, which is
close to training on the test metric. The mitigation is a held-out scene set generated from
a disjoint seed range, so an adapter is never evaluated on a scene it was trained on. The
honest claim is narrow: *the fine-tune raises the rate at which the small model produces
output the guardrail accepts, on scenes it has not seen.* Whether the guardrail is **right**
is a separate question, measured separately, by the multi-scene harness above.

---

## Current status

Working end-to-end prototype: deterministic engine, two agents on open Nemotron models, and
a deterministic validator, with 79 checks that run without an API key or network access.
76 of them need no dependencies at all. `pyright` reports zero errors across `src/` and
`scaffolding/`. Demo data is synthetic.

| | |
|---|---|
| Executable checks | **79/79** — 76 run with no dependencies at all |
| Red team, demo scene | **15/15** cases, **12/12** guardrail catch rate |
| Red team, 177 generated scenes | **2,374/2,374** cases, **1,843/1,843** guardrail catch rate |
| Deterministic path | ~1 ms per 13-detection scene |
| Continuous integration | 2 jobs on every push: one with dependencies, one with none |
| No API key, no network | all of the above runs on a laptop |

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

### Declared as outstanding

The repository does not dress up its ceilings:

- **`length_sigma_m` (2.0 m)** is a placeholder, pending calibration against real detection
  literature.
- **The scoring weights** are uncalibrated and are never presented as a probability of
  infringement.
- **Demo data is synthetic**, with a schema mirroring the real sources so that going live
  means replacing a single module.
- **The angula campaign window** is a per-jurisdiction default, not a universal legal fact.
- **The legal instrument in the EU is VMS, not AIS**, and it is confidential: shared only
  under agreement with the national administration. Without it the system reasons from AIS
  and loses part of the case. This points at integration inside the authority's environment
  rather than a rival platform.
- **Sentinel-1 revisit** is measured in days, and the small-scale fleet below 15 m largely
  falls under the sensor's detection floor.
- **A SAR detection identifies nobody.** It is an indication for directing a patrol, never
  evidence. All output is framed as resource allocation.
- **Classification under the EU AI Act is unresolved.** Use by a control authority may bring
  it within the high-risk provisions. That is a question for legal advice; the deterministic
  validator and the retained run record help either way.
- **Nobody who would use this has been spoken to yet.** It is the project's largest gap, and
  no amount of compute closes it.

### Roadmap

- **Phase 1 (done):** deterministic cross-reference, two-agent pipeline, output validator,
  patrol sequencing, the fixed-infrastructure guard, and the environmental gate.
- **Phase 2 (in progress):** a SAR vessel detector (`scaffolding/vision.py`) — CA-CFAR with
  a Lee speckle filter, numpy-only, deterministic and auditable. Still ahead: real Global
  Fishing Watch data; real Natura 2000 polygons via shapely; multimodal chip reasoning with
  `nemotron-3-nano-omni-30b-a3b-reasoning`; self-hosted NIM so operational data stays inside
  the authority's environment.
- **Phase 3 (Codefest):** LoRA fine-tune of Nemotron-3-Nano so the small model can run the
  writer role; multi-scene evaluation of the guardrail; calibration of the two placeholders;
  an evaluation harness measuring precision against known enforcement outcomes.
- **Open problem, and the one that most needs mentorship:** evaluating agentic output
  without clean ground truth. Deterministic rules catch **contradiction** (the model writes
  19 m where the record says 55). They do not catch **addition**: the model keeps every
  figure correct and appends a claim that sounds reasonable and that no fact supports.

`docs/CLOSING_REPORT.md` carries the phase-by-phase status, the verification table and the
deliberate ceilings.

---

## Quick start

```bash
# 1. Deterministic engine only — no dependencies, no API key
python src/test_caution.py     # 76 of 79 checks; the rest need the SDK
python src/eval_agent.py       # red-team harness on the demo scene
python src/main.py --cross-reference-only

# 2. The multi-scene red team — still no key, no network, no GPU
python finetune/scene_factory.py --n 200 --out data/scenes.jsonl
python finetune/harness_over_scenes.py --scenes data/scenes.jsonl

# 3. Full pipeline
pip install -r requirements.txt
export NVIDIA_API_KEY='nvapi-...'        # Windows: $env:NVIDIA_API_KEY = 'nvapi-...'
python src/main.py

# 4. Choose models per agent
export ANALYST_MODEL='nvidia/nemotron-3-super-120b-a12b'
export WRITER_MODEL='nvidia/nemotron-3-super-120b-a12b'

# 5. Live Global Fishing Watch SAR detections (falls back to demo without a token)
export GFW_TOKEN='...'                    # from globalfishingwatch.org/our-apis
python src/main.py --source gfw

# --- scaffolding: built and self-checking, outside the demo path ---
python scaffolding/vision.py              # CA-CFAR on a synthetic Sentinel-1 chip
python scaffolding/latency.py             # where the time goes
streamlit run scaffolding/app.py          # officer triage view (needs streamlit)
```

Get an API key at [build.nvidia.com](https://build.nvidia.com). One key works for every
model — the model is chosen per request, not per key.
`python src/list_models.py nemotron` lists the models available to your key.

For the fine-tuning pipeline on an HPC cluster, see
[finetune/README.md](finetune/README.md).

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
  eval_agent.py      red-team harness: guardrail catch rate on the demo scene
  validate_structure.py  structural check on the analyst response
  list_models.py     helper: list the models available to your API key

finetune/            Codefest: closing the small-model gap
  scene_factory.py   synthetic scenes — facts sampled, never model-generated
  surface_vocab.py   NeMo Data Designer config for names and languages
  gen_teacher.py     teacher generation, gated by validate.py
  curate.py          dedup, length filter, coverage report, leak-free split
  harness_over_scenes.py   the existing red team, over hundreds of worlds
  eval_live.py       live-model measurement: the model, not the guardrail
  nano_writer_lora.yaml    NeMo AutoModel LoRA recipe (8-GPU and 1-GPU variants)
  preflight_dataset.py     load the corpus as the trainer will, before the job
  sbatch_*.sh        Slurm jobs for each stage
  cluster_env.sh     every cluster-specific value, in one place
  CLUSTER_NOTES.md   what we learned about the Codefest cluster, the hard way
  CURATOR.md         where NeMo Curator fits, and why not yet

scaffolding/         built, self-checking, NOT exercised by the demo path
  vision.py          SAR vessel detector (CA-CFAR)
  curation.py        CFAR auto-candidate YOLO labels for human review
  train_detector.py  validate/split/data.yaml, TensorRT export seam
  latency.py         per-stage latency breakdown
  app.py             Streamlit triage view for an officer

demo_data/           synthetic demo data, schema mirroring the real sources
docs/SAMPLE_OUTPUT.md    full unedited output of all three stages
docs/WHY_AN_LLM.md       the case for and against the model, and what would settle it
docs/PROMPTS.md          the analyst and writer prompts, rule by rule
docs/CLOSING_REPORT.md   phase-by-phase status, verification table, ceilings
docs/DEPLOY_NIM_OCI.md   running a self-hosted Nemotron NIM on an OCI GPU shape
```

`src/` and `scaffolding/` are separated so the demo path is visible in the tree rather than
asserted in a document: nothing in `src/` imports anything from `scaffolding/`.

---

## Target users

The European Fisheries Control Agency (headquartered in Vigo, Spain) and national and
regional fisheries inspection services. Because the design is open and self-hostable, the
system can run inside the authority's own environment and its reasoning can be audited:
neither is optional when the output feeds a decision with enforcement consequences.

---

## Beyond fisheries

Nothing about the guardrail is specific to fishing. The pattern is that a language model
writes prose feeding a decision with legal consequences, so the guarantees have to live in
executable code rather than in a prompt — including the guarantee about what must never be
omitted. Customs. Tax. Environmental permitting. Benefits fraud. Anywhere an approximate
answer can attach a legal breach to someone who is complying.

Not claimed today. Fisheries is where it gets proven.

---

## Team

Four undergraduate students in Spain (Universidad Carlos III de Madrid and Universidad
Complutense). Work was divided across agent orchestration, geospatial and regulatory data,
model serving, and product and evaluation; commits were made from a shared setup, so the git
history does not map one-to-one onto contributors.

- Jorge Rodríguez Fernández
- Shengyu Chen
- Arsenii Samokhin

## License

MIT — see `LICENSE`.

## Data and model licensing

All planned data sources are open public data. Model weights are open and used under their
respective licenses; see the model card on build.nvidia.com.