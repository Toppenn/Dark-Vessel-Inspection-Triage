"""Structural validation of the analyst response.

Runs before the factual checks in validate.py, which assume the response has
the shape the prompt asked for. Kept separate from validate.py because the two
answer different questions: this one asks "is this response usable at all", and
validate.py asks "is what it says true of the dossier".

Severities match validate.py, so main.py can surface issues from both in one
place:
  BLOCKER  the response cannot be acted on or checked
  WARNING  degraded, but the rest of the pipeline can still run
"""

from typing import Any, Dict, List, Tuple

BLOCKER = "BLOCKER"
WARNING = "WARNING"

# The shape the analyst prompt asks for. A missing narrative field costs the
# reader context; it does not put a false statement in front of an inspector,
# which is what BLOCKER is reserved for.
_ANALYST_KEYS = ("prioritised_candidates", "ais_not_applicable",
                 "observed_pattern", "overall_recommendation", "limitations")


def validate_analyst_structure(data: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """Check the analyst response has the shape the prompt asked for.

    Returns (severity, where, message) tuples, the same form validate.py uses.
    Candidate ids are NOT checked against the dossier here: validate.py already
    does that, and distinguishes an id absent from the dossier from one that is
    present but not a candidate.
    """
    issues: List[Tuple[str, str, str]] = []

    for key in _ANALYST_KEYS:
        if key not in data:
            issues.append((WARNING, "analyst structure",
                           f"the response is missing '{key}', which the prompt "
                           f"asks for"))

    candidates = data.get("prioritised_candidates")
    if candidates is None:
        issues.append((BLOCKER, "analyst structure",
                       "the response carries no prioritised_candidates list: "
                       "there is nothing to act on and nothing to check"))
    elif not isinstance(candidates, list):
        issues.append((BLOCKER, "analyst structure",
                       f"prioritised_candidates is {type(candidates).__name__}, "
                       f"not a list"))
    else:
        for position, candidate in enumerate(candidates, 1):
            if not isinstance(candidate, dict) or not candidate.get("id"):
                issues.append((BLOCKER, "analyst structure",
                               f"candidate {position} carries no id, so it "
                               f"cannot be matched against the dossier"))

    return issues


def has_blockers(issues: List[Tuple[str, str, str]]) -> bool:
    return any(severity == BLOCKER for severity, _, _ in issues)