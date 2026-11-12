#!/usr/bin/env bash
# Serve nvidia/GLM-5.3-Flash-FP4-Local on TWO RTX PRO 6000 Blackwell (2 x 96 GB).
# Run ON the instance:  ssh -T <instance> 'bash -s' < scripts/serve_glm53.sh
# 320B parameters (18B active), about 166 GiB of GPU memory, 177 GB on disk.
# Keep the weights on the instance's local NVMe (/opt/dlami/nvme, 3.5 TB): the root disk
# writes and reads at 131 MB/s (23 minutes per load), the NVMe at about 3 GB/s. The NVMe
# is ephemeral: after a stop of the instance, download again (about 2 minutes):
#   sudo mkdir -p /opt/dlami/nvme/hf/hub && sudo chown -R ubuntu:ubuntu /opt/dlami/nvme/hf
#   hf download nvidia/GLM-5.3-Flash-FP4-Local --cache-dir /opt/dlami/nvme/hf/hub --max-workers 16
# Environment and flags are the model card's "2 x NVIDIA RTX PRO 6000 Blackwell" verbose
# command, unchanged, plus what our pipeline needs: an API key and 24 images per request.
# The card requires this community container; upstream vLLM cannot load the checkpoint.
# The model's own template always thinks (effort low / high / max, no off switch). This
# script serves a copy of the container's template with one line changed, so that
# FORGE_THINKING=off (chat_template_kwargs enable_thinking=false) starts the reply with an
# empty <think></think>. With thinking: FORGE_THINKING=on FORGE_REASONING_EFFORT=low
# FORGE_MAX_TOKENS=16000 (measured: 9,000 tokens per reply on average, a third cut off).
set -euo pipefail
MODEL="${MODEL:-nvidia/GLM-5.3-Flash-FP4-Local}"
IMAGE="${IMAGE:-ghcr.io/local-inference-lab/vllm:release-10152026}"
umask 077
[ -s ~/vllm.key ] || openssl rand -hex 24 > ~/vllm.key   # the API key; never commit it
HF_DIR="${HF_DIR:-/opt/dlami/nvme/hf}"
[ -d "$HF_DIR/hub" ] || { echo "no weights in $HF_DIR/hub; download first"; exit 1; }
cat > ~/glm53.env <<'ENV'
B12X_DYNAMIC_DIRECT_EXPERT_SCALES=1
B12X_DYNAMIC_SKIP_SPLIT_BARRIER_RESET=1
B12X_DYNAMIC_SPLIT_COMPUTE_MAC=224
B12X_DYNAMIC_SPLIT_FAST_PREPARE=1
B12X_DYNAMIC_SPLIT_LOW_SMEM=1
B12X_DYNAMIC_SPLIT_ROUTE_COMPUTE=1
B12X_DYNAMIC_WORK_SOURCE=persistent_grid
B12X_MHC_PDL=1
B12X_PCIE_ONESHOT_BLOCK_LIMIT=4
B12X_PCIE_ONESHOT_PDL=1
B12X_PCIE_ONESHOT_THREADS=512
B12X_W4A16_A4_PREFILL=1
B12X_W4A16_FP32_TOPK_WEIGHTS=1
CUBLAS_WORKSPACE_CONFIG=:4096:1
CUDA_DEVICE_ORDER=PCI_BUS_ID
CUTE_DSL_ARCH=sm_120a
GLOO_SOCKET_IFNAME=lo
INSTANTTENSOR_BACKEND=BUFFERED
NCCL_BUFFSIZE=1048576
NCCL_IB_DISABLE=1
NCCL_MAX_NCHANNELS=2
NCCL_MIN_NCHANNELS=2
NCCL_NET_PLUGIN=none
NCCL_P2P_LEVEL=SYS
NCCL_PROTO=LL,LL128,Simple
NCCL_SOCKET_IFNAME=lo
NCCL_TUNER_PLUGIN=none
OMP_NUM_THREADS=1
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,large_segment_size_mb:12
SAFETENSORS_FAST_GPU=1
TORCH_CUDA_ARCH_LIST=12.0a
VLLM_B12X_MLA_CKV_GATHER=1
VLLM_B12X_MLA_CKV_GATHER_MAX_TOKENS=65536
VLLM_B12X_MOE_FP4_FORCE_A16=1
VLLM_CAUSAL_CONV1D_UPDATE_HOIST=1
VLLM_DISABLED_KERNELS=MarlinFP8ScaledMMLinearKernel
VLLM_DISABLE_SHARED_EXPERTS_STREAM=0
VLLM_ENABLE_PCIE_ALLREDUCE=1
VLLM_GLM53_DFLASH_ATTN=1
VLLM_GLM53_EMBED_HOST=1
VLLM_GLM53_KDA_GATE_SIDE_STREAM=1
VLLM_GLM53_KDA_MXFP8_ACTIVATION_MODE=prefill
VLLM_GLM53_L2_PREFETCH=1
VLLM_GLM53_L2_PREFETCH_PERSIST_MB=0
VLLM_GLM53_MTP_DRAFT_HEAD=bf16
VLLM_GLM53_ONLINE_DENSE_MXFP8=0
VLLM_GLM53_SPLIT_MAMBA_BLOCK_SIZE=auto
VLLM_GLM53_SPLIT_TARGET_BLOCK_SIZE=2048
VLLM_LM_HEAD_A16=1
VLLM_MTP_NVFP4_LM_HEAD=0
VLLM_MXFP8_LM_HEAD=0
VLLM_PCIE_ALLREDUCE_BACKEND=b12x
VLLM_PCIE_DMA_MIN_BYTES=6MB
VLLM_PCIE_TWOSHOT_ALLREDUCE_MAX_SIZE=off
VLLM_PLUGINS=
VLLM_SHARE_PYNCCL_COMMS=1
VLLM_USE_FASTOKENS=1
VLLM_USE_FLASHINFER_SAMPLER=1
VLLM_USE_V2_MODEL_RUNNER=1
VLLM_WORKER_MULTIPROC_METHOD=spawn
HF_HUB_OFFLINE=1
ENV
docker rm -f vllm >/dev/null 2>&1 || true
docker run --rm --entrypoint cat "$IMAGE" /opt/lil/runtime/templates/glm53-flash.jinja \
  | sed "s/<|assistant|>{{- '<think>' -}}/<|assistant|>{{- '<think><\/think>' if (enable_thinking is defined and not enable_thinking) else '<think>' -}}/" \
  > ~/glm53-flash.jinja
grep -q "enable_thinking" ~/glm53-flash.jinja || { echo "template patch did not apply"; exit 1; }
chmod 644 ~/glm53-flash.jinja
docker run -d --name vllm --restart unless-stopped --init --gpus all \
  --network host --ipc host --shm-size 32g --stop-timeout 30 \
  --ulimit memlock=-1 --ulimit stack=67108864:67108864 \
  -v "$HF_DIR":/root/.cache/huggingface \
  -v ~/glm53-flash.jinja:/opt/forge/glm53-flash.jinja:ro \
  --env-file ~/glm53.env \
  -e VLLM_API_KEY="$(cat ~/vllm.key)" \
  --entrypoint vllm \
  "$IMAGE" \
  serve "$MODEL" \
      --host 0.0.0.0 \
      --port 8000 \
      --additional-config '{"glm53_kda_decode_backend":"auto","kda_prefill_backend":"b12x"}' \
      --attention-backend B12X \
      --block-size 256 \
      --chat-template /opt/forge/glm53-flash.jinja \
      --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE"}' \
      --cp-kv-cache-interleave-size 4 \
      --cudagraph-capture-sizes 1 2 4 8 12 16 20 24 28 32 \
      --dcp-kv-cache-interleave-size 4 \
      --decode-context-parallel-size 2 \
      --default-chat-template-kwargs '{"reasoning_effort":"max","clear_thinking":false}' \
      --dtype bfloat16 \
      --enable-auto-tool-choice \
      --enable-chunked-prefill \
      --no-enable-flashinfer-autotune \
      --enable-prefix-caching \
      --enable-prompt-tokens-details \
      --gpu-memory-utilization 0.985 \
      --kv-cache-dtype fp8 \
      --kv-cache-memory-bytes 7650410496 \
      --linear-backend b12x \
      --load-format instanttensor \
      --mamba-cache-mode align \
      --max-cudagraph-capture-size 32 \
      --max-model-len 1048576 \
      --max-num-batched-tokens 4096 \
      --max-num-seqs 8 \
      --max-parallel-prefills 1 \
      --moe-backend b12x \
      --override-generation-config '{"temperature":1.0,"top_p":0.95}' \
      --prefill-compute-share 0.4 \
      --prefill-schedule-interval 1 \
      --quantization modelopt_mixed \
      --reasoning-parser glm45 \
      --recurrent-checkpoint-policy request_boundaries \
      --speculative-config '{"method":"mtp","draft_sample_method":"probabilistic","rejection_sample_method":"standard","moe_backend":"b12x","attention_backend":"B12X","num_speculative_tokens":3}' \
      --tensor-parallel-size 2 \
      --tool-call-parser glm47 \
    --limit-mm-per-prompt '{"image": 24}'
# Notes:
# --max-num-seqs 8        the card's value; our 27 parallel requests queue
# --limit-mm-per-prompt   we send eight views plus render sheets in one request
# port 8000 on the host network; reach it with ssh -N -L 8001:localhost:8000 <instance>
echo "waiting for the server (first start compiles kernels; can take 10+ minutes)..."
until curl -sf -m 5 localhost:8000/health >/dev/null; do
  docker ps -q -f name=vllm -f status=running | grep -q . || { docker logs --tail 60 vllm; exit 1; }
  sleep 15
done
echo "ready on port 8000"
