"""List the models available to your NVIDIA API key.

Usage:
    python src/list_models.py            # all models
    python src/list_models.py nemotron   # only ones matching a keyword
"""

import os
import sys

from openai import OpenAI

BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


def main() -> int:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("NVIDIA_API_KEY is not set.\n"
              "  Windows PowerShell:  $env:NVIDIA_API_KEY = 'nvapi-...'\n"
              "  macOS / Linux:       export NVIDIA_API_KEY='nvapi-...'",
              file=sys.stderr)
        return 1

    keyword = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    client = OpenAI(base_url=BASE_URL, api_key=api_key)
    try:
        models = sorted(m.id for m in client.models.list())
    except Exception as exc:  # noqa: BLE001
        print(f"Could not list models: {exc}", file=sys.stderr)
        return 1

    matches = [m for m in models if keyword in m.lower()]

    if not matches:
        print(f"No models matching '{keyword}'. Total available: {len(models)}")
        print("Run without arguments to see the full list.")
        return 1

    print(f"{len(matches)} model(s) found:\n")
    for model_id in matches:
        print(f"  {model_id}")
    print("\nCopy the exact identifier you want and set it:")
    print("  $env:NEMOTRON_MODEL = \"<identifier>\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())