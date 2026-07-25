# Code conventions

How this repository is written, and why. Read this before adding a module or a
rule — most review comments on this project have been about a convention, not a
bug.

---

## The one idea everything follows

**Facts are computed; models interpret; code checks the interpretation.**

```
analysis.py   computes every figure, position and classification   (no LLM)
agents.py     reasons and writes prose about them                  (Nemotron)
validate.py   re-checks the prose against the figures              (no LLM)
```

A number that reaches an inspector must be traceable to `analysis.py`. If you
find yourself letting the model produce a figure, a coordinate or a
classification, stop: that is the boundary this project exists to hold.

---

## Language

- **Code, comments, docstrings, commit messages: English.** No exceptions.
- **Output to the user: configurable** (`output_language`), because an inspector
  should not read enforcement paperwork in a foreign language.
- **Spanish appears in exactly one place**: test fixtures that prove the
  validator works in the authority's working language. That is data, not code.
  Do not "translate" it — it would empty the test of meaning.

---

## Comments

Comments explain **why**, never what. The line above says what it does.

```python
# Bad — restates the code
# Set the classification to high_priority if there are 2 or more indicators
if len(firm) >= HIGH_INDICATOR_COUNT:

# Good — explains the decision, and what it cost to learn it
# Classification follows the number of independent indicators that concur, not
# a points total. Points were previously tuned around a corroboration item that
# double-counted the activity classifier; removing that double count moved
# records across a threshold it had helped set, which is proof the threshold was
# measuring the wrong thing.
if len(firm) >= HIGH_INDICATOR_COUNT:
```

**When a rule exists because something failed, say so.** Most of the validator's
rules carry a sentence naming the real failure that produced them. That is the
difference between a rule a reader trusts and one they assume is arbitrary.

**Write down the limits.** If a module cannot do something, the module says so —
`environment.py` states that SAR cannot see an angula boat; `analysis.py` states
that `length_sigma_m` is an uncalibrated placeholder. A limitation written down
is engineering; a limitation left for the reader to discover is a trap.

---

## Naming

| Kind | Convention | Example |
|---|---|---|
| Module | one word, lowercase, a noun for its responsibility | `validate.py` |
| Public function | verb first, says what it returns | `validate_report`, `angula_conditions` |
| Private helper | leading underscore | `_invariant_tokens`, `_in_season` |
| Module constant | upper snake case, defined at the top with its rationale | `HIGH_INDICATOR_COUNT` |
| Classification value | lower snake case, matches the dossier key | `high_priority`, `ais_not_applicable` |

Never abbreviate a domain term: `estimated_length_m`, not `est_len`. Units go in
the name when the value has one.

---

## Error policy

Decisive data fails **loudly**; optional data degrades quietly.

```python
# Decisive: a wrong value silently changes a legal conclusion.
if "fishing_score" not in detection:
    raise ValueError(
        f"detection {detection.get('id', '?')} has no fishing_score; a missing "
        f"activity score cannot be read as absence of activity")

# Optional: absence is a legitimate state, not an error.
gear = detection.get("likely_gear", "unknown")
```

The test for which one you have: **if a missing value would produce a different
legal conclusion without anyone noticing, it is decisive.** Length, timestamp,
closure dates and activity score are decisive. Gear and vessel name are not.

Never fall back to a default that reads as a finding. `date.today()` for a
missing timestamp is the worst kind: it silently activates or deactivates a
seasonal closure.

---

## The validator

One module, `validate.py`, holds everything that checks model output — the
analyst and the writer, structure and content. Do not start a second validator
module: a reader must not have to ask which one runs.

**Rules are numbered in the order they are read**, 1 upward. If you insert one,
renumber. Out-of-order numbering (`5, 6, 5b, 5c, 6c, 6a`) is how this file
looked before someone asked why, and they were right to ask.

**Severities mean specific things:**

| | Meaning |
|---|---|
| `BLOCKER` | The output must not reach an inspector. A false statement about a vessel, a moved coordinate, an omitted high-priority record. |
| `WARNING` | Defensible but likely wrong. A missing narrative field, a medium record left out. |

A blocker stops the report being printed and exits non-zero. Reserve it for what
would mislead someone with authority to act.

**Every rule needs a test in both directions.** The rule fires on the failure,
*and* stays silent on the legitimate case that resembles it. A test that only
proves a rule fires is half a test — that is how a rule that flagged every
correct Spanish brief survived for a week.

---

## Tests

`test_caution.py` is one file, grouped by property, printing `PASS`/`FAIL` per
check. It runs with no API key and no network, and it must stay that way: a test
suite that needs credentials is a suite nobody runs.

Test **behaviour, not wording**. The renaming of "apparent fishing activity"
broke no test precisely because the tests assert on `potential_indicators`, not
on strings.

Test descriptions state the property, not the mechanism:

```python
# Good
"a compliant vessel in transit through an integral reserve raises no indicator"
# Bad
"test assess_detection returns empty list"
```

When a real run exposes a failure, add the fixture **with the exact text that
slipped through**, and verify the test fails without the fix. A regression test
that would pass without the fix protects nothing.

---

## Configuration

Anything a jurisdiction sets goes in `demo_data/zones.json`, never in code:
thresholds, season windows, patrol base, score weights. Each gets a `_note`
sibling explaining what it is and whether it is a real value or a placeholder.

```json
"_season_note": "Regulatory, not astronomical: each autonomous community opens
                 its own angula campaign... Set it to the window published for
                 the jurisdiction being analysed.",
"season": {"start": "11-01", "end": "02-28"}
```

If a number could be challenged in a hearing, it is configuration, and its
provenance is written next to it.

---

## Repository layout

```
src/           the engine and the demo path
scaffolding/   built, self-checking, NOT exercised by the demo path
demo_data/     synthetic data whose schema mirrors the real sources
docs/          prompts, deployment, closing report, this file
```

**Nothing in `src/` imports from `scaffolding/`.** That is checkable in one
command, which is why the separation is a directory and not a paragraph.

Imports are flat (`import analysis`), because the project runs as
`python src/main.py`, not as an installed package. A scaffolding module that
needs the core uses the shared bootstrap:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
```

One pattern, not one per module. `from src.something import ...` breaks the
program: there is no package called `src` on the path.

---

## Text that reaches an inspector

- **Indicators, never offences.** "presence with a contextual fishing
  indication", not "fishing illegally".
- **Say what the sensor cannot support.** A single SAR detection has no movement
  vector, so nothing may claim observed activity.
- **Cite the provision, and only the one that applies.** Never the AIS carriage
  requirement against a vessel that is broadcasting.
- **Every brief carries its innocent explanation.** The caveat is not a
  disclaimer; it is the counter-hypothesis the inspector must rule out.
- **Anchors travel:** put the zone id in the indicator text (`RES-03`), because
  it survives translation and makes the claim checkable.

---

## Before you push

```bash
python src/test_caution.py            # all checks pass
python src/eval_agent.py              # 15/15
python src/main.py --cross-reference-only
pyright                               # 0 errors
```

And once, with a key: `python src/main.py`. The deterministic path passing
proves nothing about the agent path — an import error in `agents.py` hid behind
a "install dependencies" message for a whole commit because only the
deterministic path was ever run.

If the output text changed, regenerate the README sample from the real run.
Diff it; do not eyeball it.