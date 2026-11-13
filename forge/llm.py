"""Model access behind one small interface.

The organisers run our image against an OpenAI-compatible endpoint (for example
vLLM on our Brev machine) configured by OPENAI_BASE_URL, OPENAI_API_KEY and
OPENAI_MODEL. OpenAICompatLLM is therefore the one that ships.

Content is a list of blocks: text_block(str) or image_block(path).
"""
from __future__ import annotations

import base64
import io
import os
import sys
import threading
import time
from pathlib import Path

from PIL import Image


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def image_block(path: str | Path, max_side: int = 768) -> dict:
    """PNG image block, downscaled so eight views do not swamp a self-hosted model."""
    img = Image.open(path).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"type": "image", "data": base64.standard_b64encode(buf.getvalue()).decode("utf-8")}


# Hosted APIs cap requests in flight (Ollama Cloud pay-as-you-go: 3); above the cap they answer 429.
# All candidates of all parts share one client-side limit, so calls queue here instead of failing.
_LIMIT = int(os.environ.get("FORGE_LLM_CONCURRENCY", "0") or 0)
_SLOTS = threading.BoundedSemaphore(_LIMIT) if _LIMIT > 0 else None
_RATE_RETRIES = int(os.environ.get("FORGE_LLM_429_RETRIES", "4"))


class LLM:
    def complete(self, system: str, content: list[dict], timeout: float | None = None) -> str:
        raise NotImplementedError


class OpenAICompatLLM(LLM):
    """Any OpenAI-compatible chat endpoint. Reads OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL.

    FORGE_LLM_TIMEOUT_S (300)   longest a single call may take; a call also never outlives `timeout`
    FORGE_MAX_TOKENS (6000)     reply limit
    FORGE_THINKING (off)        off = no thinking (vLLM / Qwen chat-template switch); on = server default
    FORGE_REASONING_EFFORT      passed through as reasoning_effort when set (and thinking is on)
    FORGE_TEMPERATURE, FORGE_SEED  sampling, for repeatable runs
    FORGE_LLM_CONCURRENCY (0)   most calls in flight at once, shared by all threads; 0 = no limit
    FORGE_LLM_429_RETRIES (4)   a rate-limited call waits (5, 10, 20, 40 s) and retries, within `timeout`
    """

    def __init__(self, model: str | None = None, timeout: float | None = None):
        from openai import OpenAI

        self.timeout = timeout or float(os.environ.get("FORGE_LLM_TIMEOUT_S", "300"))
        self.client = OpenAI(timeout=self.timeout, max_retries=1)   # one retry: a dropped connection must not cost a candidate
        self.model = model or os.environ["OPENAI_MODEL"]
        self.max_tokens = int(os.environ.get("FORGE_MAX_TOKENS", "6000"))
        self.extra: dict = {}
        thinking = os.environ.get("FORGE_THINKING", "off").strip().lower()
        if thinking in ("off", "0", "false", "no"):
            self.extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        elif os.environ.get("FORGE_REASONING_EFFORT", "").strip():
            self.extra["reasoning_effort"] = os.environ["FORGE_REASONING_EFFORT"].strip()
        if os.environ.get("FORGE_TEMPERATURE", "").strip():
            self.extra["temperature"] = float(os.environ["FORGE_TEMPERATURE"])
        if os.environ.get("FORGE_SEED", "").strip():
            self.extra["seed"] = int(os.environ["FORGE_SEED"])
        self.calls = 0
        self.tokens = 0

    def complete(self, system: str, content: list[dict], timeout: float | None = None) -> str:
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append({"type": "text", "text": block["text"]})
            else:
                parts.append({"type": "image_url",
                              "image_url": {"url": "data:image/png;base64," + block["data"]}})
        from openai import RateLimitError

        end = time.monotonic() + max(5.0, timeout) if timeout else None   # the caller's deadline
        if _SLOTS is not None and not _SLOTS.acquire(timeout=None if end is None else max(end - time.monotonic(), 0.0)):
            raise TimeoutError("no free model slot before the deadline")
        try:
            for attempt in range(_RATE_RETRIES + 1):
                left = self.timeout if end is None else min(self.timeout, end - time.monotonic())
                if left < 5.0:
                    raise TimeoutError("no time left for the model call")
                try:
                    reply = self.client.chat.completions.create(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        messages=[{"role": "system", "content": system}, {"role": "user", "content": parts}],
                        timeout=left,
                        **self.extra,
                    )
                    break
                except RateLimitError:
                    wait = 5.0 * 2 ** attempt
                    if attempt == _RATE_RETRIES or (end is not None and time.monotonic() + wait + 5.0 > end):
                        raise
                    print(f"llm: rate-limited, retry in {wait:.0f}s", file=sys.stderr, flush=True)
                    time.sleep(wait)
        finally:
            if _SLOTS is not None:
                _SLOTS.release()
        choice = reply.choices[0]
        self.calls += 1
        self.tokens += getattr(reply.usage, "completion_tokens", 0) or 0
        if choice.finish_reason == "length":
            print(f"llm: reply cut off at FORGE_MAX_TOKENS={self.max_tokens} "
                  f"({len(choice.message.content or '')} chars of answer)", file=sys.stderr, flush=True)
        return choice.message.content or ""


class ScriptedLLM(LLM):
    """Offline stand-in for tests: returns canned replies in order (last one repeats)."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, content: list[dict], timeout: float | None = None) -> str:
        self.calls.append((system, content))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
