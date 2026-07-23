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
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8000"))


def _client() -> OpenAI:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is not set. Get one at build.nvidia.com, then:\n"
            "  Windows PowerShell:  $env:NVIDIA_API_KEY = 'nvapi-...'\n"
            "  macOS / Linux:       export NVIDIA_API_KEY='nvapi-...'"
        )
    return OpenAI(base_url=BASE_URL, api_key=api_key, timeout=300.0)


def _complete(model: str, system: str, user: str, temperature: float = 0.2) -> str:
    response = _client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=MAX_TOKENS,
    )
    text = "".join(c.message.content or "" for c in response.choices).strip()
    if not text:
        raise RuntimeError(
            f"Model '{model}' returned no content. It may have spent the whole "
            f"token budget on reasoning. Try raising MAX_TOKENS (currently "
            f"{MAX_TOKENS})."
        )
    return text


def _parse_json(text: str) -> dict:
    """Models sometimes wrap JSON in code fences or precede it with prose."""
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            candidate = part[4:] if part.startswith("json") else part
            if candidate.strip().startswith("{"):
                cleaned = candidate
                break
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise ValueError(
            "Could not parse JSON from the model response. First 500 chars:\n"
            + cleaned[:500]
        )


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
    return _parse_json(_complete(ANALYST_MODEL, ANALYST_SYSTEM, user))


def write_briefs(dossier: dict, prioritisation: dict) -> dict:
    """Agent 2: produce the inspection briefs."""
    user = ("Factual dossier:\n\n" + json.dumps(dossier, ensure_ascii=False, indent=2)
            + "\n\nAnalyst prioritisation:\n\n"
            + json.dumps(prioritisation, ensure_ascii=False, indent=2))
    return _parse_json(_complete(WRITER_MODEL, WRITER_SYSTEM, user, temperature=0.3))