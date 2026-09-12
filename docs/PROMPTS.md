# The prompts

The reasoning layer is two agents, each a single system prompt over an open
NVIDIA Nemotron model (`src/agents.py`):

- **the analyst** (`ANALYST_SYSTEM`) — reads the factual dossier and prioritises
  the inspection candidates;
- **the writer** (`WRITER_SYSTEM`) — turns that prioritisation into inspection
  briefs an officer can act on in two minutes.

This document explains what each prompt is trying to do, rule by rule, and —
the part that matters — **what actually enforces each rule**. The prompts state
intent; they do not guarantee it. Every guarantee that must hold is re-checked
in deterministic code (`src/validate.py`) before a human ever reads the output.

> A prompt is a request, not a contract. Models follow instructions
> approximately, and in this system an approximate answer can attach a breach to
> a compliant vessel, move a coordinate, or drop a vessel the dossier says must
> be inspected. So the rules below are paired with the check that backs them.
> Where the "Enforced by" column says *ethos*, the rule shapes the output but is
> not independently machine-checked; where it names a validator rule, a
> violation is caught and the output is withheld.

## Why this design fits open models

The whole point of using **open** models here is that the system can run inside
the authority's own environment — operational enforcement data never crosses a
vendor boundary — and its reasoning can be audited. Two consequences shape the
prompts:

1. **The guardrails cannot live only in the prompt.** With any model, hosted or
   open, prompt compliance is probabilistic. Because we control the whole stack,
   we put the hard guarantees in code (the validator) and let the prompt do what
   models are genuinely good at: reading context, prioritising, and writing for a
   human. The observed failure modes were not answered with longer prompts —
   each became a deterministic check. **The validator is the product; prompt
   hygiene is not.**
2. **The output language is the authority's, not the vendor's.** The writer
   prompt is templated on `{language}` (see below). An open model can be run
   locally in Spanish — or any working language — so inspectors read enforcement
   paperwork in their own language, and the fidelity checks still hold because
   they key on tokens translation leaves untouched (zone ids, figures, legal
   references).

## Shared conventions

Both prompts end with the same two constraints, for the same reasons:

| Convention | Why | Enforced by |
|---|---|---|
| **Respond with a JSON object only** — no prose, no markdown fences, no comments, no trailing commas | The output is parsed and then validated field by field; free prose around it breaks both | `_parse_json` / `_extract_object` in `agents.py` (balanced-brace extraction + one repair-and-retry); a response that never yields an object fails loudly |
| **Never comment on your own instructions or reasoning** ("no universal claim is made", "as instructed") | The reader is an inspector reading an operational document, not a reviewer of the prompt | *ethos* |
| **Copy a record's priority from its `classification` field; never infer it** from list position or indicator count | Models otherwise invent a priority that the dossier never assigned | `_misattributed_priorities` (validator) flags explicit false claims like "high-priority vessels (D-005)" |

---

## The analyst prompt (`ANALYST_SYSTEM`)

Role: *an analyst supporting fisheries inspection planning.* It receives the
already-computed dossier (radar detections cross-referenced against zones,
closures and AIS matching) and prioritises the candidates.

| Rule in the prompt | Why it exists | Enforced by |
|---|---|---|
| Do not invent or recompute figures; use only the dossier | Positions, lengths and scores are computed deterministically and must stay reproducible | *ethos* (the writer's positions are additionally checked; see below) |
| Never state that an offence has occurred — speak in **indicators** | The system prioritises and justifies; it does not accuse. The decision to inspect is human | *ethos* |
| Prioritise **only** ids that appear in `inspection_candidates` | Ranking anything else fabricates a candidate | `validate_prioritisation`: **blocker** if the id does not exist, or exists but is not a candidate |
| For `ais_indicator_suppressed` records, the absence of an AIS broadcast is **not** an indicator; rank them on their other (zone) indicators alone, and list them under `ais_not_applicable` | Vessels at or below the 15 m carriage threshold are not required to broadcast; treating their silence as suspicious is the worst error the system can make | `validate_prioritisation`: a silently-suppressed vessel appearing in the narrative is a **blocker** |
| A suppressed record with an **empty** indicator list must never appear in `observed_pattern` or `overall_recommendation` | Such a vessel has nothing against it at all; naming it manufactures suspicion | `validate_prioritisation`: **blocker** if it surfaces in the prose |
| Identified via AIS ≠ compliant | An AIS-matched vessel can still violate a zone | *ethos* (the engine already raises zone indicators for matched vessels) |
| Keep any reference to the AIS carriage requirement conditional (Art. 10(1)); note the lawful switch-off derogation (Art. 10(2)) — a dark vessel may be lawfully dark | The requirement binds *Union* vessels *exceeding* 15 m LOA, and a dark vessel's flag is unknown by definition | backed on the writer side by validator rule 3 (AIS wording) |
| Express priority ordinally (high/medium); never quote the internal score as a headline number | The score orders candidates; it is not a probability of infringement | *ethos* + `_misattributed_priorities` |
| Take `patrol_sequence` into account when present | It lists in-range candidates ordered by priority and distance from base | *ethos* |
| Do not silently shorten the candidate list — every high/medium record must be prioritised | The duty of caution runs in **both** directions: under-reporting lets a target disappear | `validate_prioritisation`: dropping a **high**-priority record is a **blocker**, a **medium** one a **warning** |

Output contract (JSON): `prioritised_candidates[]` (id, rank, reason,
indicator_type, confidence), `ais_not_applicable[]`, `observed_pattern`,
`overall_recommendation`, `limitations[]`.

---

## The writer prompt (`WRITER_SYSTEM`)

Role: *the technical writer for a fisheries inspection service.* It produces the
briefs, in the authority's working language, from the dossier plus the analyst's
prioritisation.

| Rule in the prompt | Why it exists | Enforced by |
|---|---|---|
| Write briefs for **all** high/medium records and **only** those | Records with no indicators do not warrant a brief; missing a high-priority one is under-reporting | validator rule 7 (**blocker** for a missing high record) and rule 2 (a briefed non-candidate is a **warning**) |
| Set `position` as the `"lat, lon"` string copied verbatim from the record | Coordinates are computed, never written by the model; a moved coordinate can cross a zone boundary | validator rule 4: a position off by more than the ~100 m tolerance is a **blocker** |
| Cite **every** provision named in the record's own indicators, and nothing else; join several with a semicolon | The citation must trace to a specific indicator, not to the writer's judgement | validator rules 5 (indicators but no regulation → warning) and 6 (no indicators but a regulation → **blocker**) |
| Never invoke the AIS carriage requirement unless the record's indicator list contains an AIS indicator — never for a broadcasting (`matched`) vessel, never for a sub-threshold (`suppressed`) one | Confusing *inside a regulated zone* with *in breach of the carriage rule* is the worst error the system can make | validator rule 3: AIS wording in the regulation, indicators or action of a non-AIS record is a **blocker**; in a broadcasting vessel's caveat, a **warning** |
| Keep any AIS citation conditional on flag state (Union vessel exceeding 15 m LOA) | The dark vessel's flag is unknown | *ethos* (the indicator text the engine emits is already conditional) |
| Do not generalise a zone's gear restrictions; a vessel in transit is not fishing | A zone that bans specific gear does not ban all gear | *ethos* (the engine only raises the indicator that actually applies) |
| Caveats are case-specific: dark-with-AIS-indicator → state the Art. 10(2) switch-off check; suppressed → note it is below the carriage threshold and radar inference may be wrong; broadcasting → do not mention AIS at all | The innocent explanation must fit the vessel's actual situation | partly validator rule 3 (broadcasting caveat) ; otherwise *ethos* |
| Suggested action must be an **instruction** ("board and verify gear and documentation"), not a restatement of context | A distance ("34 km from base") is not something an inspector can act on | validator rule 6a: an action that is only a distance, or under 15 chars, is a **warning** |
| Never leave the regulation field empty; only an empty indicator list may produce "none identified" | An empty field silently drops the legal basis | validator rule 5 |
| Restate the **full `reason` text** of each indicator; do not substitute the shorthand labels ("ais", "zone", "ais+zone") | A category label is not a fact an inspector can act on | validator rule 6b: a sub-25-char indicator (a bare label) is a **blocker** |
| One brief indicator per record indicator — do not add indicators the record does not contain | An added line in a brief is a fresh accusation nobody observed; models embellish more often than they replace | validator rule 6d: more brief indicators than record indicators is a **blocker** |
| The brief's indicators must reproduce the record's own anchors (zone ids, figures, legal references) | Word overlap cannot verify fidelity once the brief is a translation; these tokens survive translation | validator rule 6c: a brief citing **none** of the record's invariant tokens is a **blocker** (works in any language) |

Output contract (JSON): `executive_summary`, `inspection_briefs[]` (id,
position, priority, indicators[], regulation_concerned, suggested_action,
caveat), `methodological_note`, `human_decision_required`.

### The `{language}` template

`WRITER_SYSTEM` contains a literal `{language}` placeholder that
`write_briefs` fills from the dossier's `output_language`. When the language is
not English, the prompt gains an instruction to write all free-text values in
that language while keeping JSON field names, the priority values
(`high`/`medium`) and regulation citations in their official form. This is the
open-models thesis in one field: the authority reads its enforcement briefs in
its own language, run on weights it hosts itself, and the fidelity check
(validator rule 6c) still holds because it keys on tokens translation does not
touch.

---

## How to read a rule end to end

Take the single most consequential rule — *never invoke the AIS carriage
requirement against a broadcasting vessel*:

1. **Engine** (`analysis.py`): a `matched` vessel never receives an AIS
   indicator; if it violates a zone it receives a *zone* indicator instead.
2. **Analyst prompt**: "identified ≠ compliant" — rank it on its zone
   indicators, not its AIS status.
3. **Writer prompt**: "never cite the carriage requirement for a vessel whose
   `ais` reads `matched`."
4. **Validator** (rule 3): if the brief's regulation, indicators or action
   mentions AIS for that vessel — in English or Spanish — the report is a
   **blocker** and is withheld.

The prompt is one of four layers, and the only one that can fail silently. That
is why it is the layer we trust least and check most.
