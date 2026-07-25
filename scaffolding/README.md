# Scaffolding

Modules that are **not exercised by the demo path**. They live here rather than
in `src/` so that the distinction is structural: you can see what the pipeline
runs by looking at the tree, instead of taking a document's word for it.

`src/main.py`, `src/test_caution.py` and `src/eval_agent.py` import nothing from
this directory.

| Module | Role | Phase | Needs |
|---|---|---|---|
| `vision.py` | SAR vessel detector (CA-CFAR, deterministic) | 2 | `numpy` |
| `curation.py` | Turns SAR chips into candidate YOLO labels for human review | 1.2 | `numpy` |
| `train_detector.py` | Fine-tune and TensorRT export seam | 2.1 | GPU + `requirements-train.txt` |
| `latency.py` | Per-stage latency breakdown of the full flow | 4.2 | — |
| `app.py` | Streamlit triage view | 5.1 | `streamlit`, `pydeck` |

## Running them

Each module self-checks when run directly, from the repository root:

```bash
python scaffolding/vision.py           # CFAR recovery on a synthetic scene
python scaffolding/curation.py         # candidate labels from synthetic chips
python scaffolding/train_detector.py   # dataset validation, no GPU needed
python scaffolding/latency.py          # deterministic path timing
streamlit run scaffolding/app.py       # the UI
```

## Importing the core

`app.py` and `latency.py` read the engine in `src/`. Both do it the same way, at
the top of the file:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
```

One shared pattern rather than each module inventing its own. `vision.py`,
`curation.py` and `train_detector.py` need nothing from `src/` — they form a
self-contained chain (`train_detector` → `curation` → `vision`).

## Optional dependencies

`streamlit`, `pydeck` and `ultralytics` are optional by design: they belong to
the frontend and training scaffolds, not to the engine, and
`requirements-train.txt` is deliberately not installed on a CPU box. The engine
and its 67 checks run on a bare interpreter.

`pyrightconfig.json` therefore silences missing-import errors for the whole tree.
Leaving them on would keep a permanently red editor and train the eye to ignore
it — which is how a real type error goes unnoticed.
