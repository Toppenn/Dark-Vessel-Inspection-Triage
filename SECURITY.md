# Security policy

## Scope

This repository is a decision-support prototype: it runs locally or in a container,
holds no user accounts, and exposes no public endpoint. There is no service of ours
to attack. What matters instead is what the output is used for — the briefs this
system produces are read by inspection officers, so a defect that puts a false
statement in front of one is a security problem, not only a bug.

Two classes of report are in scope.

### 1. Conventional vulnerabilities

- Credential handling: `NVIDIA_API_KEY` and `GFW_TOKEN` are read from the
  environment and must never be logged, committed, or written to `last_run.json`.
- The Global Fishing Watch client in `src/data.py` and any other network path.
- The container image and its dependency chain.
- Anything that lets untrusted input reach the filesystem or the shell.

### 2. Guardrail failures

These are what this project is about, and we treat them with the same priority.

- **Fabrication that reaches the output.** A brief that states a figure, position,
  zone, or legal provision the dossier does not support, and that
  `src/validate.py` does not block. Also: a claim invented by *addition* rather
  than substitution, a legal term of art the record never cites, or a caveat that
  contradicts its own record.
- **Under-reporting.** A high-priority record dropped from the report or from the
  analyst's ranking without being flagged. The duty of caution runs in both
  directions: failing to report is as serious as accusing without basis.
- **Suppression failures in either direction.** A vessel below the AIS carriage
  threshold that still receives an AIS indicator, or — equally — a suppressed
  vessel that loses indicators it legitimately holds. A charted fixed structure
  raised as a dark-vessel candidate, or a real vessel dismissed as one.
- **Prompt injection through data.** This system consumes external data (SAR
  detections, zone registries, fleet registry fields). Text arriving through those
  channels that steers the analyst or writer is a vulnerability, not a curiosity.
- **Silent failure.** A malformed or missing critical field that is absorbed into
  a default instead of raising. Absence of data must never be read as evidence.

If you can make the pipeline emit an unsupported accusation that
`python src/eval_agent.py` does not catch, that is the report we most want.

## Supported versions

There are no tagged releases. `main` is the only supported branch; fixes land
there and nowhere else. The demo path is pinned to the committed synthetic data in
`demo_data/`, so a report should say which commit you were on.

## Reporting

Open a private report through GitHub's **Security → Report a vulnerability**, which
keeps the disclosure out of public issues until it is fixed. If that is unavailable
to you, contact a maintainer listed in the README rather than opening a public issue.

Please include: the commit hash, the command you ran, the output you got, and the
output you expected. For a guardrail failure, the most useful report is a
reproducing case — a dossier and a model response that should have been blocked and
was not.

We are four students, not a security team. Expect an acknowledgement within a week
and an honest answer about whether and when we can fix it. If we cannot, we will say
so and document the limitation rather than leave it implied.

## What is already documented, not a finding

These are known ceilings, stated in the README and `docs/CLOSING_REPORT.md`:

- `length_sigma_m` and the scoring weights are uncalibrated placeholders.
- The lexical-overlap check on brief indicators is skipped outside English; the
  invariant-token check runs in every language.
- Demo data is synthetic. The demo path never contacts the network.
- `scaffolding/` is not exercised by the demo path.

Reports on these are still welcome as improvements — just not as vulnerabilities.
