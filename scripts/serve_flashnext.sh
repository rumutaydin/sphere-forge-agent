#!/usr/bin/env bash
# Serve nvidia/Qwen3.8-Flash-Next-FP4-Local on ONE RTX PRO 6000 Blackwell (96 GB).
# Run ON the instance. Needs about 128 GB of host RAM: the 51B-parameter n-gram
# embedding (PLE) is kept in CPU memory (VLLM_PLE_CPU_OFFLOAD=1).
# Download first (about 103 GB):
#   hf download nvidia/Qwen3.8-Flash-Next-FP4-Local --cache-dir ~/hf/hub
# Environment and flags are the model card's "RTX PRO 6000 Blackwell" verbose command,
# unchanged, plus what our pipeline needs: an API key and 24 images per request.
# The card requires this community container; upstream vLLM cannot load the checkpoint.
set -euo pipefail
MODEL="${MODEL:-nvidia/Qwen3.8-Flash-Next-FP4-Local}"
IMAGE="${IMAGE:-ghcr.io/local-inference-lab/vllm:release-10152026}"
umask 077
[ -s ~/vllm.key ] || openssl rand -hex 24 > ~/vllm.key   # the API key; never commit it
mkdir -p ~/hf
cat > ~/flashnext.env <<'ENV'
B12X_DENSE_SPLITK_TURBO=1
B12X_DYNAMIC_DETERMINISTIC_OUTPUT=0
B12X_DYNAMIC_DIRECT_EXPERT_SCALES=1
B12X_DYNAMIC_SKIP_SPLIT_BARRIER_RESET=1
B12X_DYNAMIC_SPLIT_COMPUTE_MAC=224
B12X_DYNAMIC_SPLIT_FAST_PREPARE=1
B12X_DYNAMIC_SPLIT_LOW_SMEM=1
B12X_DYNAMIC_SPLIT_ROUTE_COMPUTE=1
B12X_DYNAMIC_WORK_SOURCE=persistent_grid
B12X_W4A16_A4_PREFILL=1
B12X_DISK_BACKEND=io_uring
B12X_MHC_PDL=1
B12X_PCIE_ONESHOT_BLOCK_LIMIT=4
B12X_PCIE_ONESHOT_PDL=1
B12X_PCIE_ONESHOT_THREADS=512
CUDA_BINARY_LOADER_THREAD_COUNT=8
CUDA_DEVICE_ORDER=PCI_BUS_ID
CUDA_MODULE_LOADING=LAZY
CUTE_DSL_ARCH=sm_120a
INSTANTTENSOR_BACKEND=BUFFERED
NCCL_BUFFSIZE=2097152
NCCL_CUMEM_ENABLE=0
NCCL_IB_DISABLE=1
NCCL_MAX_NCHANNELS=16
NCCL_MIN_NCHANNELS=16
NCCL_NET_PLUGIN=spcx
NCCL_P2P_LEVEL=SYS
NCCL_PROTO=LL,LL128,Simple
OMP_NUM_THREADS=2
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
SAFETENSORS_FAST_GPU=1
TORCHINDUCTOR_LOOP_ORDERING_AFTER_FUSION=0
TORCH_CUDA_ARCH_LIST=12.0a
VLLM_B12X_DENSE_ACTIVATION_MODE=auto
VLLM_B12X_MOE_FP4_FORCE_A16=1
VLLM_CAUSAL_CONV1D_UPDATE_HOIST=1
VLLM_COMPUTE_NANS_IN_LOGITS=0
VLLM_DISABLED_KERNELS=MarlinFP8ScaledMMLinearKernel
VLLM_ENABLE_PCIE_ALLREDUCE=1
VLLM_GDN_SPEC_DECODE_METADATA_FASTPATH=1
VLLM_LM_HEAD_A16=1
VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0
VLLM_MTP_NVFP4_LM_HEAD=1
VLLM_MXFP8_LM_HEAD=0
VLLM_PCIE_ALLREDUCE_BACKEND=b12x
VLLM_PLE_CPU_OFFLOAD=1
VLLM_QWEN3_8_FLASH_NEXT_HC_TP=0
VLLM_QWEN3_8_FLASH_NEXT_MTP_COMPACT=1
VLLM_QWEN3_8_FLASH_NEXT_OVERLAP=1
VLLM_SSM_CONV_STATE_LAYOUT=DS
VLLM_USE_FASTOKENS=1
VLLM_USE_V2_MODEL_RUNNER=1
VLLM_WORKER_MULTIPROC_METHOD=spawn
TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=1
TORCH_NCCL_USE_COMM_NONBLOCKING=0
HF_HUB_OFFLINE=1
ENV
docker rm -f vllm >/dev/null 2>&1 || true
docker run -d --name vllm --restart unless-stopped --init --gpus all \
  --network host --ipc host --shm-size 32g \
  --ulimit memlock=-1 --ulimit stack=67108864:67108864 \
  -v ~/hf:/root/.cache/huggingface \
  --env-file ~/flashnext.env \
  -e VLLM_API_KEY="$(cat ~/vllm.key)" \
  --entrypoint vllm \
  "$IMAGE" \
  serve "$MODEL" \
    --host 0.0.0.0 \
    --port 8000 \
    --async-scheduling \
    --block-size 64 \
    --compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE","custom_ops":["all"]}' \
    --decode-context-parallel-size 1 \
    --dtype bfloat16 \
    --enable-auto-tool-choice \
    --enable-chunked-prefill \
    --no-enable-flashinfer-autotune \
    --enable-prefix-caching \
    --enable-prompt-tokens-details \
    --gdn-decode-kernel b12x \
    --gpu-memory-utilization 0.975 \
    --kv-cache-dtype fp8 \
    --no-language-model-only \
    --linear-backend b12x \
    --load-format instanttensor \
    --mamba-cache-mode align \
    --mamba-ssm-cache-dtype auto \
    --max-cudagraph-capture-size 64 \
    --max-model-len 262144 \
    --max-num-batched-tokens 6019 \
    --max-num-seqs 16 \
    --mm-encoder-tp-mode data \
    --mm-processor-cache-gb 0.0 \
    --moe-backend b12x \
    --pipeline-parallel-size 1 \
    --quantization modelopt_mixed \
    --reasoning-parser qwen3 \
    --speculative-config '{"method":"mtp","draft_sample_method":"probabilistic","rejection_sample_method":"standard","moe_backend":"b12x","num_speculative_tokens":3}' \
    --tensor-parallel-size 1 \
    --tool-call-parser qwen3_xml \
    --limit-mm-per-prompt '{"image": 24}'
# Notes:
# --max-num-seqs 16       the card's value; our 27 parallel requests queue, which is fine
# --limit-mm-per-prompt   we send eight views plus render sheets in one request
# port 8000 on the host network; reach it with ssh -N -L 8001:localhost:8000 <instance>
echo "waiting for the server (first start compiles kernels; can take 10+ minutes)..."
until curl -sf -m 5 localhost:8000/health >/dev/null; do
  docker ps -q -f name=vllm -f status=running | grep -q . || { docker logs --tail 60 vllm; exit 1; }
  sleep 15
done
echo "ready on port 8000"
