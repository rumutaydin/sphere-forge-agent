#!/usr/bin/env bash
# Start the model server on the Brev GPU instance. Run ON the instance (ssh in first).
# Measured on one RTX PRO 6000 (96 GB): ready in about 4 minutes once the weights are
# on disk, 71 tokens/s for one request, about 870 tokens/s in total at 16 in parallel.
set -euo pipefail
MODEL="${MODEL:-Qwen/Qwen3.8-27B}"
umask 077
[ -s ~/vllm.key ] || openssl rand -hex 24 > ~/vllm.key   # the API key; never commit it
mkdir -p ~/hf
docker rm -f vllm >/dev/null 2>&1 || true
docker run -d --name vllm --restart unless-stopped --gpus all --ipc=host -p 8000:8000 \
  -v ~/hf:/root/.cache/huggingface \
  -e VLLM_API_KEY="$(cat ~/vllm.key)" \
  vllm/vllm-openai:latest \
  --model "$MODEL" \
  --max-model-len 65536 \
  --max-num-seqs 32 \
  --reasoning-parser qwen3 \
  --limit-mm-per-prompt '{"image": 24}' \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3}' \
  --gpu-memory-utilization 0.92
# Notes:
# --max-num-seqs 32          the default (1024) fails at start-up on this card
# --reasoning-parser qwen3   keeps the model's thinking out of the answer text
# --speculative-config       the model's own draft head; 26 -> 71 tokens/s per request
# --limit-mm-per-prompt      we send eight views plus render sheets in one request
echo "waiting for the server..."
until curl -sf -m 5 localhost:8000/health >/dev/null; do sleep 10; done
echo "ready on port 8000"
