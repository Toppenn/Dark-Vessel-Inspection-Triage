# Contributing

Read [`conventions.md`](conventions.md) first. It is short, and it explains the one
idea the whole repository follows:

> Facts are computed; models interpret; code checks the interpretation.

Most review comments on this project have been about a convention, not a bug.

## Before every commit

```bash
python src/main.py --cross-reference-only   # engine, no dependencies, no key
python src/test_caution.py                  # 76 of 79 checks without the SDK
python src/eval_agent.py                    # red-team harness
```

All three must pass. If you have the OpenAI SDK installed, `test_caution.py` must
report 79/79.

## The rule that matters most

**Never weaken, skip, or delete a check to make a change pass.**

A failing check is the system telling you something. Twice in this project's history
a rule was correct and a test was wrong, and both times the right fix was to the test
fixture, not to the rule. Once, a suite was overwritten and the failures disappeared
rather than being fixed — the guarantee did not break, it stopped being looked at.
That is the exact failure mode this project exists to prevent, so we do not practise
it on ourselves.

If a check fires on something you believe is correct, say so in the pull request and
explain why. Changing the assertion silently is not an option.

## Adding a rule to the validator

Every rule in `src/validate.py` exists because a model produced that failure in a
real run. If you add one:

- Say in the pull request which failure it catches and where you saw it.
- Add both directions to `src/test_caution.py`: a case the rule must flag, and a
  well-formed case it must leave alone. The second matters more — a rule that fires
  on correct output is worse than no rule, because it teaches people to ignore
  warnings.
- Add the adversarial case to `src/eval_agent.py` if it is a new failure family.
- Choose the severity deliberately. BLOCKER means a false statement could reach an
  inspector. WARNING means the output is degraded but safe.

## Adding to the engine

`src/analysis.py` computes; it never calls a model. A change that makes an LLM
produce a figure, a position, a distance or a classification is out of scope for this
repository, whatever else it improves.

Missing critical data must raise, not default. Absence of data is never evidence.

## Scaffolding

`scaffolding/` holds modules that are built and self-checking but not exercised by
the demo path. Keep that boundary: if something becomes part of the demo path, it
moves to `src/` and gets checks in `test_caution.py`.

## Style

Follow what is already there rather than a linter's opinion. Comments explain *why*,
not what — if a rule or threshold has a reason, the reason belongs next to it.
`pyright` runs clean over `src/` and `scaffolding/`; keep it that way.
