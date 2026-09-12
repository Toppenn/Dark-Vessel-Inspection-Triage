# NeMo Curator: what it would do here, and why `curate.py` exists anyway

The mentor suggested [NeMo Curator](https://github.com/NVIDIA-NeMo/Curator) for
the data curation pipeline. This records what was actually evaluated, so the
choice is a decision rather than an omission.

## What Curator is

A GPU-accelerated data curation toolkit built on RAPIDS (cuDF, cuML, cuGraph)
and Ray, with a pluggable executor. It handles text, image, video and audio;
for text it provides loaders, language identification, heuristic and
classifier-based quality filtering, exact and fuzzy (MinHash/LSH) and semantic
deduplication, PII redaction and synthetic-data generation stages. Installation
for the GPU text path pulls a CUDA 12 stack and expects roughly 16 GB of GPU
memory and network access to Hugging Face.

It is the right tool when the corpus is large enough that deduplication is a
distributed graph problem.

## Why the pipeline does not start there

The corpus this project needs is on the order of a few hundred to a few
thousand agent traces: a dossier, an analyst prioritisation, a writer report.
At that scale a Ray cluster is not throughput, it is a dependency. Concretely:

* `curate.py` runs on the login node, in CI, and on a laptop, with no GPU, no
  Ray and no CUDA — the same property the engine, the validator and the 79
  checks already have, and the one that makes the whole repository auditable by
  someone who has not been given a cluster account.
* The two curation steps that matter most here are **not** generic. Splitting
  by *scene* rather than by sample (so an analyst trace and the writer trace
  derived from it cannot land on opposite sides of the split) and reporting
  coverage per *case template* (so a corpus that quietly dropped every
  near-threshold record is visible) are project-specific. They would be custom
  stages in Curator too.
* The heaviest filter in this pipeline is not a Curator stage at all. It is
  `validate.py`, applied in `gen_teacher.py`: a sample enters the corpus only
  if the same executable rules that gate a real report accept it.

## Stage-by-stage mapping

If the corpus grows past what fits in memory — real GFW scenes at national
scale, or multi-model teacher ensembles — this is the migration path.

| `curate.py` stage | Curator equivalent |
|---|---|
| well-formedness (assistant turn must parse as JSON) | custom `ProcessingStage`, or a score filter over a parse predicate |
| agent filter | column filter on the loader |
| exact dedup on (prompt, completion) | `ExactDuplicates` (hash-based, GPU) |
| near-dup on the user turn, 5-gram Jaccard ≥ 0.85 | `FuzzyDuplicates` (MinHash + LSH + connected components on cuGraph) |
| length filter by approximate tokens | `WordCountFilter` / token-count heuristic filters |
| — (not implemented here) | semantic dedup via embeddings; quality classifiers |
| case-coverage and language report | custom stage; no built-in equivalent |
| leak-free split by scene seed | custom; Curator's splits are sample-wise |

The honest summary for the write-up: Curator was evaluated, its
deduplication stages map cleanly onto what this pipeline does, and it is the
right answer at a scale this project has not reached. Running a distributed
GPU curation framework over two thousand JSON documents would be a claim, not
an engineering decision.

## Where Data Designer *is* used

See `surface_vocab.py`. Data Designer generates the surface vocabulary — place
names, designations, closure reasons, port names, working language — and is
deliberately kept out of the facts, which are sampled deterministically and
turned into dossiers by `src/analysis.py`. A model-invented dossier would put
the model's own errors into the supervision signal and falsify the project's
governing rule at training time as well as at inference time.
