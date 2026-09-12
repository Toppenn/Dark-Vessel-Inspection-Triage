# Why this project needs a language model

*Written in answer to a mentor's question during the NVIDIA Open Models Codefest
2026. It is deliberately written against the project, not for it.*

---

## The objection, in its strongest form

The deterministic engine already computes everything that matters. Look at what
`src/analysis.py` emits for a single detection:

> **Indicator:** radar-estimated length 22.0 m is above the 15.0 m threshold
> beyond sensor uncertainty and no AIS broadcast was matched; if this is a Union
> fishing vessel exceeding 15.0 m LOA, the AIS carriage and operation requirement
> is potentially concerned (Article 10(1), Council Regulation (EC) No 1224/2009,
> as amended by Regulation (EU) 2023/2842)

That is not a feature vector. It is a finished sentence, in the correct legal
register, with the citation attached and the conditionality intact — produced by
code, with no model involved.

So the objection writes itself: **if the engine already produces prose, what is
the model for?** Assemble those strings into a document with an f-string. It
will be faster, free, deterministic, auditable line by line, and it cannot
hallucinate.

This objection deserves a straight answer, because the project is one where an
unnecessary model is not a neutral cost. The output feeds a decision with
enforcement consequences; every component has to justify its presence.

## The uncomfortable part: the baseline already exists, and it passes

The repository contains a working template baseline and has since before this
question was asked. `src/eval_agent.py` builds `clean_report()` — a report
assembled deterministically from the dossier — and runs it through the same
validator that gates the real output. It passes clean, on every scene, every
time. Over 130 generated scenes it passes 134 times out of 134.

The honest conclusion from that is uncomfortable and worth stating first:
**validator pass rate cannot be the argument for the model.** A template wins
that comparison by construction, because a template derived from the dossier
cannot contradict the dossier. Any claim that the LLM earns its place has to be
made on ground the template baseline does not already own.

There are four such grounds. Two are strong. Two are weaker than they look.

## 1. The caveat field — the weaker argument, stated honestly

Every brief carries an *innocent explanation that could account for the
indicator*. On the demo data this is templatable: there are three zone types,
two AIS states and a handful of indicator kinds, so a lookup table of
explanations covers the space.

It stops being templatable at the scale the system targets. The real regulatory
layer is Natura 2000 marine plus national and regional closures: dozens of zone
types, gear categories with per-jurisdiction exceptions, seasonal windows that
move between campaigns, derogations that apply to some fleets and not others.
The innocent explanation for a 16 m vessel dark inside a seasonal closure in
February is not the innocent explanation for the same vessel in the same place
in August, and neither is a row in a table anyone will maintain.

But note what this argument actually is: an argument about **marginal
maintenance cost**, not about capability. A sufficiently determined engineer can
template all of it. The question is who writes those rules, and who rewrites
them when Regulation (EU) 2023/2842 is amended again.

## 2. Working language — a real constraint, often overlooked

Briefs are written in the working language of the authority that will act on
them. `output_language` is in the regulatory layer, not in the prompt, and the
writer honours it.

An inspector should not read enforcement paperwork in a foreign language. For
the EU that means Spanish, Portuguese, French, Greek, Italian, Croatian, and
regional working languages beneath those. A template library must be authored
**and legally reviewed** once per language: the conditional phrasing of an
Article 10(1) reference is exactly the kind of sentence that a careless
translation turns into an accusation.

A model produces all of them from the same facts, and the factual validator
checks the result in every language through invariant tokens — zone ids,
figures, legal references — that survive translation. This is also the clearest
reason the models must be **open and self-hostable** rather than a vendor API:
a commercial provider optimises for the languages with a market. A fisheries
control service in Galicia is not that market.

## 3. Cross-record reasoning — where the template has nothing to offer

The per-record text is the easy half. The analyst produces `observed_pattern`,
`overall_recommendation` and `limitations`: the connective tissue across a whole
scene. *These four detections cluster on the western edge of the reserve, two of
them dark and above threshold, over a single tide; the pattern is consistent
with a single group working the boundary, and the closest candidate is not the
one to attend first.*

That is a judgement about a set, conditioned on geometry, timing, patrol
capacity and what the data cannot show. A template emits per-record paragraphs
and stops. Concatenating them does not produce that paragraph, and it is the
paragraph an inspection coordinator actually reads.

## 4. Who can change it — the institutional argument

A template library is code. Changing it requires an engineer, a release and a
test pass. A prompt plus an executable validator can be changed by the domain
expert who understands the regulation, with the guarantees still enforced
underneath by rules that do not move.

For a system meant to live inside a control authority rather than beside it,
that is not a convenience. It decides whether the thing is maintainable by the
organisation that owns it, or permanently dependent on whoever built it.

## The reframing that matters

Underneath all four points is a structural answer that is more honest than any
of them.

**The language model is deliberately not load-bearing, and that is the design.**

Positions, distances, scores, classifications, threshold applications and every
legal citation are computed by code and validated against the dossier
afterwards. The model interprets and writes over data that arrives already
computed. Remove it and the system still works: it produces the deterministic
report, in one language, without the cross-record narrative. It degrades. It
does not break.

So when someone says *a template could do most of this*, the correct response is
not to deny it. It is: **yes — and that is precisely why a language model is
permitted here at all.** An architecture in which removing the LLM is
catastrophic is an architecture that has given the LLM authority over facts. This
one has not. The model sits in the one place where being wrong is recoverable,
because the guardrail catches it and the report is withheld.

That is the transferable claim, and it is the one worth defending at GTC.
Customs, tax, environmental permitting, benefits fraud — anywhere a model writes
prose that feeds a decision with legal consequences, the question is never
"is the model good enough". It is "what happens on the day it is wrong". This
project's answer is executable, runs on every change, and includes a guarantee
about what must never be **omitted** — which is the half that systems of this
kind usually forget.

## What would settle it

None of the above is a measurement, and it should not be presented as one. The
argument that the briefs are better is currently an assertion. Two things would
turn it into evidence:

**An A/B with the people who would use it.** The same twenty scenes, template
briefs and model briefs, blind, put in front of inspection staff at a control
authority, scored on: time to decide, whether the caveat changed the decision,
and whether anything in the text was wrong or misleading. This is the single
highest-value experiment available to the project and it needs no GPU. It is
blocked on the same gap the roadmap already names as the largest one — nobody
who would use this has been spoken to yet.

**A template-vs-model run through `eval_live.py`.** Cheap, and it produces the
negative result honestly: both will pass the validator at a high rate, and the
comparison will show that the validator is not measuring the thing being argued
about. Publishing that is better than not running it, because it draws the line
between what the guardrail proves and what it does not.

Until the first of those exists, the defensible statement is narrow, and it is
the one to make:

> The engine decides. The model writes, in the authority's language, over facts
> it did not compute and cannot alter, and code checks the writing before anyone
> sees it. The model is here because writing is the part that does not reduce to
> a rule — and it is allowed to be here because everything that does reduce to a
> rule has been taken away from it.
