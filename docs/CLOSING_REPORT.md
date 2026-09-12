# Closing report — Dark Vessel Inspection Triage

**Open Models Codefest 2026 (NVIDIA · Oracle · Open Hackathons)**

Public-sector use case: decision support for fisheries inspection planning —
prioritising where limited patrol capacity should go next, for the European
Fisheries Control Agency and national and regional inspection services.

---

## 1. Executive summary

The project delivers an **agentic triage system** that orchestrates the ReAct
loop — environmental context → SAR acquisition → detection → AIS cross-reference
→ reporting — on **open NVIDIA Nemotron models**, with one design property that
makes it legitimate rather than a suspicion generator: **the duty of caution runs
in both directions, and it is guaranteed in code, not in the prompt**.

Scaffolding for all **five roadmap phases** stands and is **verified by
executable checks** (no key, no network, no cost).

**Codefest update (September 2026).** Two of the external resources arrived — an
NVIDIA API key and GPU time on Curiosity v2 — and two things were done with them.
First, the guardrail's evidence base was widened from 15 adversarial cases on one
demo scene to **2,374 cases across 177 independently generated scenes**, all on
expected severity. Second, a fine-tuning pipeline was built (`finetune/`) to close
the one capability gap the model table records: the 30B model cannot complete the
writer task, and the whole self-hosting argument is weaker while the system needs
a 120B model. Real SAR imagery and detector training remain outside.

---

## 2. The thesis

> A prompt is a request, not a contract. Models follow instructions
> approximately, and here an approximate answer can **attribute a breach to a
> compliant vessel**, move a coordinate, or **silently drop a vessel the dossier
> says must be inspected**.

Hence the two decisions that govern all the code:

1. **Deterministic / reasoning separation.** Positions, geometry, legal
   thresholds and scores are computed in a pure, auditable engine
   (`analysis.py`). The LLM never invents a figure; it reasons and prioritises
   over facts already computed. *In an enforcement file, the data cannot come
   out of a generative model.*
2. **The validator is the product.** Every guarantee that must hold is
   **re-checked in code** (`validate.py`) before a human reads the output. If the
   model hallucinates, the output is **withheld** and the process exits non-zero.

**Bidirectional duty of caution**, the central property:

- *Do not over-report*: nothing is accused. The system prioritises and justifies;
  the decision to inspect is always human. Absence of AIS is **not** an indicator
  for vessels below the legal carriage threshold (15 m, Art. 10(1) Reg. (EC)
  1224/2009), which are not required to broadcast.
- *Do not under-report*: dropping a high-priority target is as serious as
  accusing without basis. Omitting a high-priority record is a **blocker**.

---

## 3. Architecture

```
  Phase 3 · ReAct loop                        Separation of concerns
  ─────────────────────────                   ───────────────────────────────
  Step 1  Environmental context  environment.py  (season/moon/tide → scan priority)
  Step 2  SAR acquisition        vision.py       (CA-CFAR, deterministic, numpy)
  Step 3  Detection              vision.py       (position, length, confidence)
  Step 4  AIS cross-reference    analysis.py     (deterministic engine = the tool)
  Step 5  Incident reporting     agents.py       (analyst + writer, Nemotron)
                                 validate.py     (guardrail: withholds on hallucination)
                                 app.py / main.py (Streamlit frontend / CLI)
```

The agents run against an **OpenAI-compatible** endpoint (`NVIDIA_BASE_URL`).
That makes **self-hosting a Nemotron NIM a matter of changing one environment
variable, with zero code changes** — the "open models inside the authority's own
environment" thesis is literal (see `docs/DEPLOY_NIM_OCI.md`).

### Where the angula gate sits

`environment.py` reports a **scanning-priority signal**, not a per-vessel
indicator: it ranks which nights and estuaries are worth tasking, given the
campaign season, moon illumination and spring/neap tendency. It never
contributes to any vessel's score, and a regression test asserts that swinging
the label from `out_of_season` to `high` moves no score at all.

Its scope limit is stated in the module itself: angula is fished from shore or
small craft inside estuaries, below SAR's ~15 m detection floor, whereas the
detections this system reasons about are 9-31 m vessels in open water. The gate
prioritises estuary tasking; **Sentinel-1 vessel detection is not the sensor that
would observe an angula boat.**

---

## 4. Roadmap status by phase

| Phase | Objective | Delivered | Verification |
|---|---|---|---|
| **1.2** Preprocessing + labelling | Radar denoise, label vessels | `curation.py`: Lee filter + CFAR → **candidate** YOLO labels plus manifest, for human review | Self-check: 3/3 targets → valid YOLO labels |
| **1.1 / 1.3** SAR dataset / environment DB | Historic Sentinel-1, tide/AIS database | `.npy` loader ready; environment layer and simulated data (`environment.py`, `data.py`) | — (needs Copernicus/ASF download) |
| **2.1** Vision fine-tune + TensorRT | Optimised lightweight detector | `train_detector.py`: validates/splits/emits `data.yaml`; TRT export as a GPU seam | Self-check: curate→validate→split→yaml; rejects a corrupt label |
| **2.2** Agentic system prompt | Surveillance agent role | `agents.py` (analyst + writer); documented in `docs/PROMPTS.md` | Rule by rule, each with the check that backs it |
| **3** Agentic flow (ReAct) | Autonomous five-step loop | Complete (see §3) | End-to-end deterministic pipeline |
| **4.1** Reasoning evaluation | Avoid hallucination and false positives | `eval_agent.py` (guardrail red-team); `finetune/harness_over_scenes.py` (the same red team over generated worlds); **fixed-infrastructure** suppression in the engine | 12/12 adversarial, 15/15 overall on the demo scene; **1,843/1,843 adversarial, 2,374/2,374 overall across 177 generated scenes** |
| **4.2** Latency optimisation | Measure the full flow | `latency.py`: per-stage breakdown | Deterministic path ~1 ms / 13 detections |
| **5.1** Frontend | Alerts for the field officer | `app.py` (Streamlit + pydeck map) | Headless AppTest |
| **5.2** Documentation | Prompts and open models | `docs/PROMPTS.md`, `docs/WHY_AN_LLM.md`, this report | — |
| **6** Domain fine-tune (Codefest) | Make the small open model usable for the writer role | `finetune/`: deterministic scene generation, validator-gated distillation from Super-120B, curation, LoRA SFT on Nemotron-3-Nano-30B-A3B, live before/after evaluation | Pipeline runs end to end; corpus generated; **adapter not yet trained — no result claimed** |

**Packaging (5.x):** `Dockerfile` (CPU-only app) plus `docs/DEPLOY_NIM_OCI.md`
(NIM on OCI, GPU shapes, container wiring).

---

## 5. Artefact inventory

The tree separates what the demo path exercises from what it does not.

**Core engine and reasoning — `src/`:**

| File | Role |
|---|---|
| `analysis.py` | Deterministic cross-reference engine — the tool the agents call |
| `validate.py` | Checks model output against the dossier; blocks on failure |
| `validate_structure.py` | Structural check on the analyst response, before the factual ones |
| `agents.py` | Nemotron agents: analyst + writer |
| `environment.py` | Environmental context gate (season/moon/tide) — scan priority |
| `geo.py` | Point-in-polygon and distance; shapely optional for real GeoJSON |
| `data.py` | Data loading — the boundary that changes to go live (GFW adapter) |
| `main.py` | CLI orchestrator |
| `test_caution.py` | 79 checks: duty of caution, invariants, validator rules |
| `eval_agent.py` | Red-team harness (Phase 4.1): guardrail catch rate |
| `list_models.py` | Helper: list the models available to an API key |

**Scaffolding — `scaffolding/`.** Not exercised by the demo path, kept out of
`src/` so the distinction is structural rather than a claim in a document. Each
module runs its own self-check and imports the core through one shared bootstrap.

| File | Role | Phase |
|---|---|---|
| `vision.py` | SAR detector (CA-CFAR) — the Step-3 detector | 2 |
| `curation.py` | Data curation: auto-candidate labels | 1.2 |
| `train_detector.py` | Training scaffold, TensorRT export seam | 2.1 |
| `latency.py` | Latency breakdown | 4.2 |
| `app.py` | Streamlit triage view | 5.1 |

**Fine-tuning and multi-scene evaluation — `finetune/`.** Added during the
Codefest. Imports `src/` (it runs the real engine and the real validator); nothing
in `src/` imports it. No generated artefact is committed.

| File | Role |
|---|---|
| `scene_factory.py` | Synthetic scenes: facts sampled deterministically from named case templates, never model-generated |
| `surface_vocab.py` | NeMo Data Designer config — varies place names, designations and working language only |
| `gen_teacher.py` | Distillation from Super-120B, gated by `validate.py`: a sample enters the corpus only if the report-blocking rules accept it |
| `curate.py` | Dedup, length filter, per-case coverage report, split by scene rather than by sample |
| `harness_over_scenes.py` | Runs `eval_agent.build_cases()` over every generated scene |
| `eval_live.py` | Measures the *model* (collapse / unparseable / blocked / clean), where `eval_agent.py` measures the *checker* |
| `preflight_dataset.py` | Loads the corpus exactly as the trainer will, before a job is submitted |
| `nano_writer_lora_1gpu.yaml` / `_8gpu.yaml` | NeMo AutoModel LoRA recipes |
| `sbatch_*.sh`, `cluster_env.sh` | Slurm jobs and one place for every cluster-specific value |
| `CLUSTER_NOTES.md`, `CURATOR.md` | What the cluster taught us; where NeMo Curator fits and why not yet |

**Docs and packaging:** `docs/PROMPTS.md`, `docs/WHY_AN_LLM.md`,
`docs/DEPLOY_NIM_OCI.md`, this report, `Dockerfile`, `requirements.txt` (core,
installable in ten seconds), `requirements-train.txt` (detector training, GPU,
deliberately isolated), `finetune/requirements-finetune.txt` (the LLM pipeline,
also isolated).

---

## 6. Verification (reproducible, no key, no network)

| Check | Result |
|---|---|
| `test_caution.py` — duty of caution, invariants, validator rules | **79/79** |
| `eval_agent.py` — guardrail against LLM hallucination, demo scene | **15/15** (12/12 adversarial) |
| `harness_over_scenes.py` — the same red team over 177 generated scenes | **2,374/2,374** (1,843/1,843 adversarial, 531/531 controls) |
| `vision.py` — CFAR recovery on a synthetic scene | **4/4 targets**, 0 false |
| `curation.py` — candidate YOLO labels | 3/3, valid format |
| `train_detector.py` — training-ready dataset + corrupt-label rejection | OK |
| `geo.py` — ray-cast and GeoJSON branch (with and without shapely) | OK |
| `environment.py` — season gate, year-crossing window, score isolation | OK |
| `latency.py` — deterministic path | **~1 ms / 13 detections** |
| `pyright` — static type check over `src/` and `scaffolding/` | **0 errors** |

Failure families covered by the guardrail red-team: id hallucination,
over-reporting (non-candidate, resurrecting a suppressed vessel, briefing a fixed
structure), under-reporting (dropping a high-priority record), coordinate
integrity, **AIS misattribution** (citing the carriage requirement against a
broadcasting vessel — the worst error the system can make), and fabrication
(regulation without indicators, added indicator, category label, fabricated
tokens that survive translation).

---

## 7. Deliberate ceilings (engineering honesty)

What does **not** run in this repository, marked and not pretended:

- **CNN/TensorRT detector:** today the detector is CA-CFAR (classical,
  deterministic, auditable, runs on CPU with numpy). The fine-tuned detector
  plugs into the `detect_vessels(backend='trt')` seam once weights exist. *There
  is no fake YOLO.*
- **Real training:** `train_detector.py --train` performs the fine-tune and TRT
  export **only if** a GPU and framework are present; otherwise it fails with an
  instruction. **It never reports a metric it did not measure.**
- **Curation labels:** these are **CFAR auto-candidates for human review**, marked
  `review_status: pending`. Over-trusting them would teach the detector CFAR's
  own false positives — stated explicitly.
- **Angula gate season window:** the default follows a published Cantabrian
  campaign, but the dates are set per autonomous community and move between
  campaigns. It is configuration, and it is a placeholder in exactly the way
  `length_sigma_m` is one.
- **GFW HTTP layer / live model calls:** the GFW→schema mapping is tested against
  the real data model; the HTTP layer and live Nemotron models need a token, a
  key and network, with a fallback to demo data.
- **The fine-tune is distillation, and no result is claimed yet.** The pipeline in
  `finetune/` runs end to end and the corpus generates, but no adapter has been
  trained and no before/after number exists. When it does, three things must be
  said with it: the corpus is synthetic; it is filtered by the same validator used
  to score the outcome (mitigated by a disjoint held-out seed range, not
  eliminated); and the result would show that the small model produces output the
  guardrail accepts more often, not that it reasons better.
- **The multi-scene harness measures the checker, not the world.** 2,374/2,374 says
  the guardrail generalises past the demo geometry. It does not say the guardrail
  is complete — it catches the failure modes we thought to encode. Catching
  *addition* rather than *contradiction* remains open, and is the item that most
  needs outside input.

The `ponytail:` convention marks every cut corner in the code with its ceiling
and its route to improvement.

---

## 8. What remains for production

None of it is scaffolding code; these are **external resources** that fit into
seams already defined:

1. **Real SAR data:** download Sentinel-1 GRD chips (Copernicus Data Space / ASF)
   as `.npy` → `curation.py --input`.
2. **Verified labels:** review the CFAR candidates (clear `pending`).
3. **GPU and detector training:** `pip install -r requirements-train.txt` on a GPU
   host → `train_detector.py --train` → TensorRT `.engine` → the `backend='trt'`
   seam. This is the *vision* detector and is unrelated to item 3b.
3b. **LLM fine-tune:** `finetune/` — generate the corpus, LoRA-SFT
   Nemotron-3-Nano-30B-A3B, evaluate base vs adapter on held-out scenes. Needs one
   GPU and an API key or a self-hosted teacher; see `finetune/README.md`.
4. **Live data:** `GFW_TOKEN` (real SAR detections) and `NVIDIA_API_KEY`, or a
   self-hosted NIM (reasoning).
5. **Real polygons:** load Natura 2000 / WDPA layers as GeoJSON geometry
   (`geo.py` already consumes them via shapely).
6. **Calibration:** `length_sigma_m` against Paolo et al. 2024; scoring weights
   against real inspection outcomes; the angula season window against the
   campaign published for the jurisdiction.

---

## 9. How to run it

See `README.md`. With no key and no network, the tests, the evaluation harness,
the latency breakdown, the SAR detector, curation and the training scaffold all
run as they are. With resources: Nemotron models (hosted or NIM), live GFW, GPU
training.

The figures in §6 reproduce by running the files listed — the core from `src/`,
the scaffolding from `scaffolding/`.
