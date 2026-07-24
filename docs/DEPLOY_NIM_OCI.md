# Self-hosting the reasoning model: Nemotron NIM on OCI

The whole "open models" argument of this project is that the reasoning layer can
run **inside the authority's own environment** — no enforcement data crosses a
vendor boundary. This note shows how to make that literal: run a Nemotron NIM on
an Oracle Cloud (OCI) GPU shape and point the app at it.

There is **no code change**. The agent layer (`src/agents.py`) already speaks the
OpenAI-compatible protocol against `NVIDIA_BASE_URL`. A NIM exposes exactly that
protocol on `/v1`. Self-hosting is one environment variable:

```
NVIDIA_BASE_URL=http://<nim-host>:8000/v1
```

The two containers, side by side:

```
┌─────────────────────────┐        OpenAI /v1 (HTTP)        ┌──────────────────────┐
│  app  (this Dockerfile)  │  ───────────────────────────▶  │  Nemotron NIM        │
│  engine + agents + UI    │   NVIDIA_BASE_URL points here   │  (GPU, from NGC)     │
│  CPU-only, :8501         │                                 │  :8000               │
└─────────────────────────┘                                 └──────────────────────┘
```

---

## 1. Pick an OCI GPU shape to fit the model

The NIM needs to fit the model's weights in VRAM. Match the shape to the
Nemotron variant you serve (`NEMOTRON_MODEL`):

| Model | Rough VRAM | OCI shape (example) |
|---|---|---|
| `nemotron-3-nano-30b-a3b` | ~1× 40–80 GB GPU | `VM.GPU.A10.2` / `VM.GPU.A100.1` |
| `nemotron-3-super-120b-a12b` (default) | 2–4× 80 GB | `BM.GPU.A100-v2.8` / `BM.GPU.H100.8` |
| `nemotron-3-ultra-550b-a55b` | 8× 80 GB | `BM.GPU.H100.8` |

For a hackathon demo the **nano** model on a single A10/A100 is the cheapest path
that runs end to end; set `NEMOTRON_MODEL=nvidia/nemotron-3-nano-30b-a3b` and you
can even run the *analyst* on nano and keep the *writer* larger via
`ANALYST_MODEL` / `WRITER_MODEL`.

Provision the instance from the OCI console (Compute → Instances → the GPU shape
above) using the **NVIDIA GPU Cloud Machine Image** (Oracle Marketplace), which
ships the driver + container toolkit. Open port `8501` (the app) in the subnet
security list; keep `8000` (the NIM) private to the VCN.

## 2. Authenticate to NGC and pull the NIM

The NIM images live in NVIDIA's registry. Get an **NGC API key** from
`ngc.nvidia.com` (or reuse the `nvapi-...` key from build.nvidia.com):

```bash
export NGC_API_KEY=nvapi-...
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
```

The exact image name and tag are **model-specific and versioned** — copy them
from the model's *Deploy → Docker* tab on build.nvidia.com. They look like:

```bash
export NIM_IMAGE=nvcr.io/nim/nvidia/nemotron-3-nano-30b-a3b:latest   # tag from the Deploy tab
docker pull "$NIM_IMAGE"
```

## 3. Run the NIM

```bash
mkdir -p ~/.cache/nim                       # persists the downloaded weights
docker run -d --name nim --gpus all \
  --shm-size=16g \
  -e NGC_API_KEY \
  -v ~/.cache/nim:/opt/nim/.cache \
  -p 8000:8000 \
  "$NIM_IMAGE"
```

First start downloads and optimises the engine (several minutes). It is ready
when this returns the served model id:

```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
```

Use that exact id as `NEMOTRON_MODEL` — a NIM serves one model under one name,
and the app sends it verbatim in the `model` field.

## 4. Point the app at the NIM

```bash
docker build -t pesca-furtiva .
docker run -d --name app \
  -e NVIDIA_BASE_URL=http://<nim-host>:8000/v1 \
  -e NVIDIA_API_KEY="$NGC_API_KEY" \
  -e NEMOTRON_MODEL=<served-id-from-step-3> \
  -e GFW_TOKEN="$GFW_TOKEN" \
  -p 8501:8501 \
  pesca-furtiva
```

A self-hosted NIM does not check the API key, but the OpenAI client still sends
one, so any non-empty `NVIDIA_API_KEY` is fine.

### Both containers together (docker compose)

On the same GPU host, one file wires them so the app reaches the NIM by service
name (`http://nim:8000/v1`):

```yaml
services:
  nim:
    image: ${NIM_IMAGE}
    environment: [NGC_API_KEY]
    volumes: ["~/.cache/nim:/opt/nim/.cache"]
    shm_size: "16gb"
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]
  app:
    build: .
    depends_on: [nim]
    environment:
      NVIDIA_BASE_URL: http://nim:8000/v1
      NVIDIA_API_KEY: ${NGC_API_KEY}
      NEMOTRON_MODEL: ${NEMOTRON_MODEL}
      GFW_TOKEN: ${GFW_TOKEN:-}
    ports: ["8501:8501"]
```

```bash
NIM_IMAGE=$NIM_IMAGE NEMOTRON_MODEL=<served-id> docker compose up -d
```

## 5. Smoke test the whole path

The deterministic engine needs no model, so verify it independently first
(inside the app container, no GPU required):

```bash
docker run --rm pesca-furtiva python src/main.py --cross-reference-only
```

Then confirm the reasoning layer reaches the NIM:

```bash
docker exec app python src/main.py    # full pipeline through the self-hosted NIM
```

If the second command fails on connection, the app cannot see the NIM — check
`NVIDIA_BASE_URL` and that port 8000 is reachable from the app container. If it
fails on the model id, re-read step 3: the served name must match
`NEMOTRON_MODEL` exactly.
