"""Agent layer built on open NVIDIA Nemotron models.

Two specialised agents:
  1. analyst -> reasons over the factual dossier and prioritises candidates
  2. writer  -> turns that prioritisation into inspection briefs

Design principle: the system PRIORITISES and JUSTIFIES. It does not accuse,
and it does not conclude that an offence has occurred. The decision to inspect
is always human, and every output traces back to the data that produced it.
"""

import json
import os

from openai import OpenAI

BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# NOTE: verify the exact model identifier in the build.nvidia.com catalogue.
# Model names change; override with the NEMOTRON_MODEL environment variable.
MODEL = os.environ.get("NEMOTRON_MODEL", "nvidia/nemotron-3-super")


def _client() -> OpenAI:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is not set. Get one at build.nvidia.com, then:\n"
            "  Windows PowerShell:  $env:NVIDIA_API_KEY = 'nvapi-...'\n"
            "  macOS / Linux:       export NVIDIA_API_KEY='nvapi-...'"
        )
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def _complete(system: str, user: str, temperature: float = 0.2) -> str:
    response = _client().chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=1500,
    )
    return "".join(c.message.content or "" for c in response.choices).strip()


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in code fences; strip them before parsing."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1:
            return json.loads(cleaned[start:end + 1])
        raise


ANALYST_SYSTEM = """You are an analyst supporting fisheries inspection planning.
You receive a factual dossier that has already been computed: radar detections
cross-referenced against regulated zones, seasonal closures and AIS matching.

NON-NEGOTIABLE RULES:
- Do not invent or recompute figures. Use only what is in the dossier.
- Never state that an offence has occurred. You speak in terms of INDICATORS
  that do or do not justify an inspection.
- Detections classified as 'non_assessable' fall below the legal AIS carriage
  threshold. Never prioritise them, and state explicitly why they are excluded.
- A vessel identified via AIS can still show indicators. Do not confuse
  'identified' with 'compliant'.

Respond with a JSON object ONLY, no surrounding text and no markdown:
{
  "prioritised_candidates": [
    {"id": "...", "rank": 1, "reason": "1-2 sentences citing specific dossier figures",
     "indicator_type": "...", "confidence": "high|medium|low"}
  ],
  "excluded_by_caution": ["id: legal reason for exclusion"],
  "observed_pattern": "is there a relevant spatial or temporal clustering?",
  "overall_recommendation": "2-3 sentences for the inspection coordinator",
  "limitations": ["what this analysis cannot know"]
}"""

WRITER_SYSTEM = """You are the technical writer for a fisheries inspection service.
You produce inspection briefs in clear, precise English so that an inspector can
decide within two minutes which position to attend.

RULES: do not invent data; never assert offences, only indicators; every brief
must be traceable back to its source data.

Respond with a JSON object ONLY, no surrounding text and no markdown:
{
  "executive_summary": "100-150 words on the analysed scene",
  "inspection_briefs": [
    {"id": "...", "position": "lat, lon", "priority": "high|medium|low",
     "indicators": ["..."], "regulation_concerned": "...",
     "suggested_action": "...",
     "caveat": "an innocent explanation that could account for the indicator"}
  ],
  "methodological_note": "one sentence on the limits of the method, for the file",
  "human_decision_required": "exactly what the responsible officer must decide"
}"""


def prioritise(dossier: dict) -> dict:
    """Agent 1: prioritise candidates and reason over the scene as a whole."""
    user = "Factual dossier:\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)
    return _parse_json(_complete(ANALYST_SYSTEM, user))


def write_briefs(dossier: dict, prioritisation: dict) -> dict:
    """Agent 2: produce the inspection briefs."""
    user = ("Factual dossier:\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)
            + "\n\nAnalyst prioritisation:\n\n"
            + json.dumps(prioritisation, ensure_ascii=False, indent=2))
    return _parse_json(_complete(WRITER_SYSTEM, user, temperature=0.3))
