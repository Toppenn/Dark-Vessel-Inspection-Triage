"""Agent layer built on open NVIDIA Nemotron models.

Two specialised agents:
  1. analyst -> reasons over the factual dossier and prioritises candidates
  2. writer  -> turns that prioritisation into inspection briefs

Each agent can run on a different model, so we can measure the quality/latency
trade-off across the Nemotron 3 family rather than assuming the largest model
is the right choice.

Design principle: the system PRIORITISES and JUSTIFIES. It does not accuse,
and it does not conclude that an offence has occurred. The decision to inspect
is always human, and every output traces back to the data that produced it.
"""

import json
import os
import re

import validator_llm

from openai import OpenAI

BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Nemotron 3 family, all with free hosted endpoints on build.nvidia.com:
#   nvidia/nemotron-3-nano-30b-a3b      fast, 1M context, tool calling
#   nvidia/nemotron-3-super-120b-a12b   agentic reasoning, good default
#   nvidia/nemotron-3-ultra-550b-a55b   largest, noticeably slower
#
# Phase 2 (multimodal reasoning over Sentinel-1 image chips):
#   nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"

MODEL = os.environ.get("NEMOTRON_MODEL", DEFAULT_MODEL)
ANALYST_MODEL = os.environ.get("ANALYST_MODEL", MODEL)
WRITER_MODEL = os.environ.get("WRITER_MODEL", MODEL)

# Nemotron 3 models are reasoning models: part of the token budget is spent on
# internal reasoning before the answer. Too low a ceiling truncates the JSON.
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "16000"))

# Where the raw model response is written when it cannot be parsed, so that a
# malformed response can be inspected rather than guessed at.
RAW_DUMP_PATH = "last_raw_response.txt"


def _client() -> OpenAI:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is not set. Get one at build.nvidia.com, then:\n"
            "  Windows PowerShell:  $env:NVIDIA_API_KEY = 'nvapi-...'\n"
            "  macOS / Linux:       export NVIDIA_API_KEY='nvapi-...'"
        )
    return OpenAI(base_url=BASE_URL, api_key=api_key, timeout=600.0)


def _complete(model: str, messages: list, temperature: float) -> str:
    response = _client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=MAX_TOKENS,
    )
    return "".join(c.message.content or "" for c in response.choices).strip()


def _extract_object(text: str) -> str:
    """Return the first balanced {...} block, ignoring braces inside strings.

    A naive first-brace/last-brace slice breaks as soon as the model writes any
    prose after the object, or any stray brace inside it.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    # Unbalanced: the response was cut off mid-object.
    raise ValueError("JSON object is not closed (response likely truncated; "
                     f"try raising MAX_TOKENS, currently {MAX_TOKENS})")


def _repair(fragment: str) -> str:
    """Fix the small deviations models commonly produce."""
    # Strip // line comments that sit outside strings.
    fragment = re.sub(r'(?m)^\s*//.*$', '', fragment)
    # Remove trailing commas before a closing brace or bracket.
    fragment = re.sub(r',(\s*[}\]])', r'\1', fragment)
    return fragment


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if "```" in cleaned:
        for part in cleaned.split("```"):
            candidate = part[4:] if part.lstrip().startswith("json") else part
            if "{" in candidate:
                cleaned = candidate
                break

    fragment = _extract_object(cleaned)
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        return json.loads(_repair(fragment))


def _complete_json(model: str, system: str, user: str,
                   temperature: float = 0.2) -> dict:
    """Call the model and parse JSON, retrying once on a malformed response."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    raw = ""
    for attempt in (1, 2):
        try:
            raw = _complete(model, messages, temperature)
            if not raw:
                raise ValueError("model returned no content")
            if _looks_degenerate(raw):
                raise ValueError(
                    f"model '{model}' collapsed into a repetition loop and never "
                    f"produced an object. This is a capability failure, not a "
                    f"formatting one: use a larger model for this agent")
            return _parse_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt == 2:
                try:
                    with open(RAW_DUMP_PATH, "w", encoding="utf-8") as f:
                        f.write(raw)
                except OSError:
                    pass
                raise RuntimeError(
                    f"Could not parse a JSON object from {model} after two "
                    f"attempts ({exc}). The raw response was written to "
                    f"{RAW_DUMP_PATH} so it can be inspected."
                ) from exc
            # Retry with the failure fed back in, which is usually enough.
            messages = messages + [
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content":
                    "That response could not be parsed as JSON. Reply again with "
                    "the JSON object only: no explanation before or after it, no "
                    "markdown fences, no comments, no trailing commas. Start your "
                    "reply with the opening brace and end it with the closing brace."},
            ]
    raise AssertionError("unreachable")


ANALYST_SYSTEM = """You are an analyst supporting fisheries inspection planning.
You receive a factual dossier that has already been computed: radar detections
cross-referenced against regulated zones, seasonal closures and AIS matching.

NON-NEGOTIABLE RULES:
- Do not invent or recompute figures. Use only what is in the dossier.
- Never state that an offence has occurred. You speak in terms of INDICATORS
  that do or do not justify an inspection.
- Prioritise ONLY ids that appear in inspection_candidates. Every id you rank
  is checked in code against the dossier; ranking anything else blocks the run.
- Records with "ais_indicator_suppressed": true are at or below the legal AIS
  carriage threshold: for them the absence of an AIS broadcast is NOT an
  indicator and must never be presented as suspicious. If such a record still
  appears in inspection_candidates, that is on the strength of its OTHER
  indicators (zone violations); rank it on those alone. List these records
  under "ais_not_applicable" with the reason the AIS indicator is suppressed.
- A record with ais_indicator_suppressed true AND an empty potential_indicators
  list must not appear anywhere in observed_pattern or overall_recommendation.
- A vessel identified via AIS can still show indicators. Do not confuse
  identified with compliant.
- The AIS carriage and operation requirement is Article 10(1), Council
  Regulation (EC) No 1224/2009, as amended by Regulation (EU) 2023/2842. It
  binds Union fishing vessels exceeding 15 m LOA; a dark vessel's flag state is
  unknown, so keep any reference to the requirement conditional. Under
  Article 10(2) the master may switch off the AIS where the safety or security
  of the crew is imminently at risk, and must notify the switch-off and its
  reason. A dark vessel may therefore be lawfully dark; never present darkness
  alone as conclusive.
- Express priority ordinally (high/medium) and, in prose, as "N independent
  indicators concur". Never quote the internal score as a headline number.
- If patrol_sequence is present, take it into account: it lists the candidates
  within patrol range, ordered by priority and distance from the patrol base.

NEVER comment on your own instructions, constraints or reasoning process. The
reader is an inspector reading an operational document, not a reviewer of your
prompt. Statements such as "no universal claim is made" or "as instructed" must
not appear.

When you name a record's priority in prose, copy it from that record's
`classification` field. Do not infer it from position in a list or from how many
indicators it has, and do not state counts you have not read from
`classification_summary`.

Respond with a JSON object ONLY: no text before or after it, no markdown fences,
no comments, no trailing commas.
{
  "prioritised_candidates": [
    {"id": "...", "rank": 1, "reason": "1-2 sentences citing specific dossier facts",
     "indicator_type": "...", "confidence": "high|medium|low"}
  ],
  "ais_not_applicable": ["id: why the AIS indicator is suppressed for this record"],
  "observed_pattern": "is there a relevant spatial or temporal clustering?",
  "overall_recommendation": "2-3 sentences for the inspection coordinator",
  "limitations": ["what this analysis cannot know"]
}

EXAMPLE OF DESIRED OUTPUT:
{
  "prioritised_candidates": [
    {
      "id": "D-010",
      "rank": 1,
      "reason": "High-priority candidate with two independent indicators: radar-estimated length 26.5 m exceeds AIS threshold (no AIS match) and contextual fishing indication inside integral reserve RES-03 where all gear is prohibited.",
      "indicator_type": "ais+zone",
      "confidence": "high"
    },
    {
      "id": "D-005",
      "rank": 2,
      "reason": "Medium-priority candidate; AIS indicator suppressed due to length below threshold, but single zone indicator: contextual fishing indication inside integral reserve RES-03 where all gear is prohibited.",
      "indicator_type": "zone",
      "confidence": "medium"
    }
  ],
  "ais_not_applicable": [
    "D-005: estimated length 9.5 m is below the 15.0 m AIS carriage threshold; absence of AIS broadcast is not an indicator per Article 10(1)."
  ],
  "observed_pattern": "Candidates D-010 and D-005 are clustered near the Islote Sur Integral Reserve.",
  "overall_recommendation": "Task the closest patrol unit to verify activity inside RES-03, prioritizing D-010 due to potential AIS non-compliance.",
  "limitations": [
    "Cannot confirm vessel flag state, actual gear deployed, or whether any AIS suppression is lawfully derogated under Article 10(2).",
    "Radar-derived length estimates have uncertainty; true length may fall below or above the AIS thresholds.",
    "Contextual fishing indications are non-observational and require corroboration during inspection."
  ]
}"""

WRITER_SYSTEM = """You are the technical writer for a fisheries inspection service.
You produce inspection briefs in clear, precise {language} so that an inspector can
decide within two minutes which position to attend.

RULES: do not invent data; never assert offences, only indicators; every brief
must be traceable back to its source data.

SCOPE: write briefs for ALL records classified high_priority or medium_priority
(exactly the records in inspection_candidates), and for nothing else. Records
with no indicators do not warrant a brief, and every high-priority record MUST
receive one: under-reporting is checked in code and blocks the report just as
over-reporting does.

PRIORITY: express priority ordinally (high/medium) only. Never quote the
internal score as a number; where useful, write "N independent indicators
concur".

POSITIONS AND DISTANCES: set the position field as the string "lat, lon",
copied verbatim from the record. Positions are validated in code against the
dossier and any altered coordinate blocks the whole report. If the record
carries distance_from_base_km, state it in the suggested_action (e.g. "34 km
from base").

CITING REGULATIONS, STRICT:
- Cite EVERY provision named in that record's own potential_indicators list, and
  nothing else. If there are several, join them with a semicolon. A zone-based
  provision (a gear prohibition, a seasonal closure) is a citable provision and
  applies regardless of whether the vessel is broadcasting.
- Write: none identified — ONLY when the potential_indicators list is empty. If
  the list has entries, it must produce a citation.
- NEVER cite the AIS carriage requirement unless the record's own indicator list
  contains an AIS indicator. In particular: never for a vessel whose ais field
  reads matched (it is broadcasting), and never for a vessel with
  ais_indicator_suppressed true (it is below the carriage threshold). Confusing
  inside a regulated zone with in breach is the worst error this system can make.
- Keep any AIS citation conditional on flag state, as the indicator itself is:
  the requirement binds Union fishing vessels exceeding 15 m LOA and a dark
  vessel's flag is unknown — "if this is a Union fishing vessel exceeding 15 m
  LOA, the AIS carriage and operation requirement is potentially concerned
  (Article 10(1), Council Regulation (EC) No 1224/2009, as amended by
  Regulation (EU) 2023/2842)".
- Do not generalise a zone's gear restrictions. A zone that prohibits specific
  gear does not prohibit all gear, and a vessel in transit is not fishing.

CAVEATS:
- For a dark vessel whose record contains an AIS indicator, state the lawful
  derogation — Article 10(2), Council Regulation (EC) No 1224/2009, as amended
  by Regulation (EU) 2023/2842: the master may switch off AIS where crew safety
  or security is imminently at risk — and turn it into a verifiable action:
  check whether an AIS switch-off notification was filed for this time window
  (Art. 10(2)).
- For a vessel with ais_indicator_suppressed true, the caveat must note that
  the vessel is below the AIS carriage threshold, that the absence of a
  broadcast is not an indicator, and that radar-based activity inference may be
  wrong. Never cite the carriage requirement for it.
- For a broadcasting vessel, the caveat must not mention AIS at all.

SUGGESTED ACTION: an instruction the inspector can follow ("board and verify
gear and documentation"), never a restatement of context. A distance on its own
is not an action. 
STRICT SCOPE LIMIT: Actions must remain strictly within administrative and
inspection authority. NEVER suggest judicial or enforcement actions such as
"seize", "confiscate", "arrest", or "impound".

REGULATION FIELD: never leave it empty. If the record has indicators, name the
provision each one concerns. Only an empty indicator list may produce
"none identified".

INDICATORS FIELD: restate, in full, the `reason` text of each entry in that
record's `potential_indicators`. Do not substitute the analyst's shorthand
category labels ("ais", "zone", "ais+zone") — those name a category, not a fact
an inspector can act on. One brief indicator per record indicator.

CAVEAT: it must be consistent with that record's own data. Do not suggest an
explanation the record already rules out — for example, do not call a 28 m
vessel "below the AIS carriage threshold", and do not say a closure is inactive
when the dossier lists it as active.

EXECUTIVE SUMMARY: describe the set accurately, using the figures in
classification_summary. Records differ from one another: some are AIS-matched
and some are not. Set the position field as the string "lat, lon".

NEVER comment on your own instructions, constraints or reasoning process. The
reader is an inspector reading an operational document, not a reviewer of your
prompt. Statements such as "no universal claim is made" or "as instructed" must
not appear.

When you name a record's priority in prose, copy it from that record's
`classification` field. Do not infer it from position in a list or from how many
indicators it has, and do not state counts you have not read from
`classification_summary`.

Respond with a JSON object ONLY: no text before or after it, no markdown fences,
no comments, no trailing commas.
{
  "executive_summary": "100-150 words on the analysed scene",
  "inspection_briefs": [
    {"id": "...", "position": "lat, lon", "priority": "high|medium",
     "indicators": ["..."], "regulation_concerned": "...",
     "suggested_action": "...",
     "caveat": "an innocent explanation that could account for the indicator"}
  ],
  "methodological_note": "one sentence on the limits of the method, for the file",
  "human_decision_required": "exactly what the responsible officer must decide"
}"""


def _agent_payload(dossier: dict) -> dict:
    """The dossier minus the parts an agent does not need.

    `records` holds every detection; `inspection_candidates` and
    `ais_indicator_suppressed` together already contain every record an agent
    writes about. Sending both duplicates each vessel, roughly a third of the
    prompt, and gives a model two copies of the same object to reconcile.
    """
    return {k: v for k, v in dossier.items() if k != "records"}


def _looks_degenerate(text: str) -> bool:
    """Detect a model stuck repeating one sentence instead of answering.

    Small models under a long prompt sometimes collapse into a loop and emit
    thousands of words without ever producing the object. Failing fast with a
    clear message beats a confusing parse error.
    """
    if len(text) < 2000 or "{" in text:
        return False
    sentences = [s.strip() for s in text.split(".") if s.strip()]
    if len(sentences) < 20:
        return False
    return len(set(sentences)) / len(sentences) < 0.1


def prioritise(dossier: dict) -> dict:
    """Agent 1: prioritise candidates and reason over the scene as a whole."""
    user = ("Factual dossier:\n\n"
            + json.dumps(_agent_payload(dossier), ensure_ascii=False, indent=2))
    
    # Complete the completion call to receive the structured analyst response
    data = _complete_json(ANALYST_MODEL, ANALYST_SYSTEM, user)
    
    # Validate structure and guard against hallucinated candidate IDs
    structure = validator_llm.validate_analyst_structure(data)
    if validator_llm.has_blockers(structure):
        raise ValueError(
            "Analyst response is structurally unusable:\n"
            + "\n".join(f"- {message}" for _, _, message in structure))
        
    return data


def write_briefs(dossier: dict, prioritisation: dict) -> dict:
    """Agent 2: produce the inspection briefs.

    Briefs are written in the working language of the authority that will act on
    them, set by `output_language` in the regulatory layer. Inspectors should not
    have to read enforcement paperwork in a foreign language, and open models can
    be run locally in languages a vendor API may not prioritise.
    """
    language = dossier.get("output_language", "English")
    system = WRITER_SYSTEM.replace("{language}", language)
    if language.lower() != "english":
        system += (f"\n\nWrite all free-text values in {language}. Keep the JSON "
                   f"field names and the priority values (high/medium) in English, "
                   f"and keep regulation citations in their official form.")

    user = ("Factual dossier:\n\n"
            + json.dumps(_agent_payload(dossier), ensure_ascii=False, indent=2)
            + "\n\nAnalyst prioritisation:\n\n"
            + json.dumps(prioritisation, ensure_ascii=False, indent=2))
    return _complete_json(WRITER_MODEL, system, user, temperature=0.3)