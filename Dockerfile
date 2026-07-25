# The application container: deterministic engine + agent layer + Streamlit UI.
# It is CPU-only and tiny — the GPU lives in the Nemotron NIM, a separate
# container this app reaches over HTTP (NVIDIA_BASE_URL). See
# docs/DEPLOY_NIM_OCI.md for running the NIM on an OCI GPU shape and wiring the
# two together.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so a code edit does not re-run pip.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The engine, the scene data, and the Streamlit view that reads them. The
# scaffolding directory is needed because the UI lives there; the training and
# curation modules it also contains are inert without their optional
# dependencies, which this CPU image deliberately does not install.
COPY src/ ./src/
COPY scaffolding/ ./scaffolding/
COPY demo_data/ ./demo_data/

# Non-root: the app never needs to write outside /app.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# NVIDIA_BASE_URL defaults to the hosted build.nvidia.com endpoint; override it
# to point at a self-hosted NIM (e.g. http://nim:8000/v1). NVIDIA_API_KEY is
# passed at run time (-e), never baked into the image.
EXPOSE 8501
CMD ["streamlit", "run", "scaffolding/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true"]
