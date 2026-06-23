#!/usr/bin/env bash
# =============================================================================
# download_models.sh — THE ONLY SCRIPT ALLOWED TO TOUCH THE NETWORK.
#
# Run this ONCE during the offline-prep phase, BEFORE air-gapping the box
# (README §1.1). It fetches the local GGUF models into data/models/. At runtime
# the application NEVER downloads anything; if a model file is missing it fails
# loudly (or you can set llm.mock: true to use the deterministic offline engine).
#
# Usage:
#   bash scripts/download_models.sh            # fast 3B fallback (recommended for live demo)
#   bash scripts/download_models.sh --prod     # also fetch the 7B production target
#
# After downloading, set in config/settings.yaml:
#   llm.mock: false
#   llm.model_path: data/models/<the .gguf you downloaded>
# then verify integrity and re-run `make verify-airgap` before disconnecting.
# =============================================================================
set -euo pipefail

MODELS_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/models"
mkdir -p "$MODELS_DIR"

# --- Model sources (Hugging Face GGUF mirrors). Pin to specific files. --------
FALLBACK_NAME="qwen2.5-3b-instruct-q4_k_m.gguf"
FALLBACK_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"

PROD_NAME="mistral-7b-instruct-v0.2.Q4_K_M.gguf"
PROD_URL="https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf"

# Optional local embedding model (sentence-transformers). Default build uses the
# offline hashing embedder and needs none of this.
EMBED_REPO="sentence-transformers/all-MiniLM-L6-v2"

fetch() {
  local url="$1" out="$2"
  if [ -f "$out" ]; then
    echo "[skip] already present: $out"
    return 0
  fi
  echo "[get ] $url"
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail --retry 3 -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$out" "$url"
  else
    echo "ERROR: need curl or wget to download models." >&2
    exit 1
  fi
}

echo "Downloading fast fallback model (3B) -> $MODELS_DIR/$FALLBACK_NAME"
fetch "$FALLBACK_URL" "$MODELS_DIR/$FALLBACK_NAME"

if [ "${1:-}" = "--prod" ]; then
  echo "Downloading production target (7B) -> $MODELS_DIR/$PROD_NAME"
  fetch "$PROD_URL" "$MODELS_DIR/$PROD_NAME"
fi

echo
echo "Done. Files in $MODELS_DIR:"
ls -lh "$MODELS_DIR" || true
echo
echo "NEXT STEPS (still online):"
echo "  1) (optional) embeddings: huggingface-cli download $EMBED_REPO --local-dir data/models/minilm"
echo "     then set rag.embedding.backend: sentence-transformers and NEURALINK_EMBED_MODEL_PATH."
echo "  2) Record checksums:  sha256sum data/models/*.gguf > data/models/SHA256SUMS"
echo "  3) Set llm.mock: false and llm.model_path in config/settings.yaml."
echo "  4) Run 'make verify-airgap' and confirm GREEN, then air-gap the box."
