"""Surface vocabulary — the one place NeMo Data Designer is used, and why.

Data Designer generates synthetic records with an LLM. That is exactly the
wrong tool for the *facts* of this system: the dossier is computed, and a
model-invented dossier would poison the supervision signal with the model's own
errors (see the note at the top of `scene_factory.py`).

It is the right tool for the *surface*. A corpus built from one study area,
three zone names and one patrol base teaches the writer to pattern-match on
"Islote Sur" rather than on the structure of an indicator. What we want varied
is: place names, designations, closure reasons, port names, working language —
everything that must not change the reasoning.

That split is the defensible answer to "did you just bolt a synthetic-data tool
onto the project": Data Designer varies what may vary, and is kept out of what
may not.

    # with an endpoint configured (build.nvidia.com or a local vLLM server)
    python finetune/surface_vocab.py --n 60 --out data/surface_vocab.jsonl

    # no endpoint, no network: the static pool below is used instead
    python finetune/scene_factory.py --n 200      # falls back automatically
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# A static pool, so the whole pipeline runs with no endpoint, no key and no
# network — the same property the engine and the test suite already have.
STATIC_POOL = [
    {"study_area": "Gulf of Cadiz (synthetic)",
     "mpa_name": "Bajo de los Corales Marine Protected Area",
     "closure_name": "Northern Fishing Ground - seasonal spawning closure",
     "closure_reason": "spawning season",
     "reserve_name": "Islote Sur Integral Reserve",
     "patrol_base_name": "Port of Cadiz patrol base (synthetic)",
     "structure_name": "Bajo de los Corales research platform (synthetic)",
     "output_language": "English"},
    {"study_area": "Ria de Vigo approaches (synthetic)",
     "mpa_name": "Cies Shelf Marine Protected Area",
     "closure_name": "Outer Ria - juvenile hake closure",
     "closure_reason": "juvenile aggregation",
     "reserve_name": "Cabo Home Integral Reserve",
     "patrol_base_name": "Port of Vigo patrol base (synthetic)",
     "structure_name": "Cies aquaculture cage array (synthetic)",
     "output_language": "Spanish"},
    {"study_area": "Alboran Sea (synthetic)",
     "mpa_name": "Seco de los Olivos Marine Protected Area",
     "closure_name": "Alboran Ridge - seasonal sardine closure",
     "closure_reason": "sardine spawning",
     "reserve_name": "Isla de Alboran Integral Reserve",
     "patrol_base_name": "Port of Almeria patrol base (synthetic)",
     "structure_name": "Alboran navigation buoy AL-4 (synthetic)",
     "output_language": "Spanish"},
    {"study_area": "Bay of Biscay - Cantabrian shelf (synthetic)",
     "mpa_name": "Capbreton Canyon Marine Protected Area",
     "closure_name": "Cantabrian shelf - anchovy closure",
     "closure_reason": "anchovy spawning",
     "reserve_name": "Punta del Faro Integral Reserve",
     "patrol_base_name": "Port of Santander patrol base (synthetic)",
     "structure_name": "Biscay offshore wind turbine BW-11 (synthetic)",
     "output_language": "English"},
    {"study_area": "Algarve continental shelf (synthetic)",
     "mpa_name": "Pedra do Valado Marine Protected Area",
     "closure_name": "Southern shelf - octopus closure",
     "closure_reason": "octopus reproduction",
     "reserve_name": "Ponta da Piedade Integral Reserve",
     "patrol_base_name": "Port of Faro patrol base (synthetic)",
     "structure_name": "Algarve fixed platform AP-2 (synthetic)",
     "output_language": "Portuguese"},
    {"study_area": "Gulf of Lion (synthetic)",
     "mpa_name": "Golfe du Lion Marine Protected Area",
     "closure_name": "Rhone plume - seasonal nursery closure",
     "closure_reason": "nursery protection",
     "reserve_name": "Cap Creus Integral Reserve",
     "patrol_base_name": "Port of Sete patrol base (synthetic)",
     "structure_name": "Lion offshore wind turbine LW-3 (synthetic)",
     "output_language": "French"},
]

FIELDS = list(STATIC_POOL[0].keys())


def load_vocab(path: str | Path) -> list:
    """Return the generated pool if it exists, else the static one."""
    p = Path(path)
    if not p.exists():
        return STATIC_POOL
    rows = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if all(f in row and row[f] for f in FIELDS):
                rows.append({f: row[f] for f in FIELDS})
    return rows or STATIC_POOL


# --- Data Designer config ----------------------------------------------------

LANGUAGES = ["English", "Spanish", "Portuguese", "French"]

COASTS = [
    "the Gulf of Cadiz", "the Galician rias", "the Alboran Sea",
    "the Cantabrian shelf", "the Algarve shelf", "the Gulf of Lion",
    "the Balearic shelf", "the Adriatic north shelf", "the Aegean north shelf",
    "the Irish Sea western approaches", "the Kattegat", "the Gulf of Riga",
]

STRUCTURE_KINDS = ["offshore wind turbine", "fixed research platform",
                   "aquaculture cage array", "navigation buoy"]


def build_config():
    """Build the Data Designer config. Imported lazily so this module stays
    importable (for STATIC_POOL) on a machine without data-designer."""
    import data_designer.config as dd

    b = dd.DataDesignerConfigBuilder()

    b.add_column(dd.SamplerColumnConfig(
        name="coast", sampler_type=dd.SamplerType.CATEGORY,
        params=dd.CategorySamplerParams(values=COASTS)))
    b.add_column(dd.SamplerColumnConfig(
        name="output_language", sampler_type=dd.SamplerType.CATEGORY,
        params=dd.CategorySamplerParams(values=LANGUAGES)))
    b.add_column(dd.SamplerColumnConfig(
        name="structure_kind", sampler_type=dd.SamplerType.CATEGORY,
        params=dd.CategorySamplerParams(values=STRUCTURE_KINDS)))

    model = os.environ.get("DD_MODEL_ALIAS", "nvidia-text")

    b.add_column(dd.LLMTextColumnConfig(
        name="study_area", model_alias=model,
        prompt="Invent a plausible but FICTIONAL maritime study area name for a "
               "sea region near {{ coast }}. Output the name only, ending with "
               "the word '(synthetic)'. No explanation."))
    b.add_column(dd.LLMTextColumnConfig(
        name="mpa_name", model_alias=model,
        prompt="Invent a plausible but FICTIONAL name for a marine protected "
               "area in {{ study_area }}, in the style of a Natura 2000 marine "
               "site. It must end with 'Marine Protected Area'. Name only."))
    b.add_column(dd.LLMTextColumnConfig(
        name="reserve_name", model_alias=model,
        prompt="Invent a plausible but FICTIONAL name for an integral marine "
               "reserve in {{ study_area }}. It must end with 'Integral "
               "Reserve'. Name only."))
    b.add_column(dd.LLMTextColumnConfig(
        name="closure_name", model_alias=model,
        prompt="Invent a plausible but FICTIONAL name for a seasonal fishing "
               "closure area in {{ study_area }}, of the form '<place> - "
               "<something> closure'. Name only."))
    b.add_column(dd.LLMTextColumnConfig(
        name="closure_reason", model_alias=model,
        prompt="In three words or fewer, give the biological reason for the "
               "seasonal closure '{{ closure_name }}' (for example 'spawning "
               "season', 'juvenile aggregation'). Lower case, no full stop."))
    b.add_column(dd.LLMTextColumnConfig(
        name="patrol_base_name", model_alias=model,
        prompt="Invent a plausible but FICTIONAL fisheries patrol base name "
               "serving {{ study_area }}, of the form 'Port of <name> patrol "
               "base (synthetic)'. Name only."))
    b.add_column(dd.LLMTextColumnConfig(
        name="structure_name", model_alias=model,
        prompt="Invent a plausible but FICTIONAL name for a charted "
               "{{ structure_kind }} in {{ study_area }}, ending with "
               "'(synthetic)'. Name only."))

    return b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--out", default="data/surface_vocab.jsonl")
    ap.add_argument("--preview", action="store_true",
                    help="show one record and exit without generating")
    args = ap.parse_args()

    try:
        from data_designer.interface import DataDesigner
    except ImportError:
        print("data-designer is not installed. The pipeline will use the "
              "static pool in surface_vocab.STATIC_POOL "
              f"({len(STATIC_POOL)} entries), which is fine for a first run.\n"
              "  pip install data-designer", file=sys.stderr)
        return 1

    builder = build_config()
    designer = DataDesigner()

    if args.preview:
        designer.preview(config_builder=builder).display_sample_record()
        return 0

    result = designer.create(config_builder=builder, num_records=args.n)
    df = result.dataset if hasattr(result, "dataset") else result

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in df.to_dict(orient="records"):
            fh.write(json.dumps({f: str(row.get(f, "")).strip() for f in FIELDS},
                                ensure_ascii=False) + "\n")
    print(f"{args.n} surface-vocabulary rows written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
