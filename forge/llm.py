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


class LLM:
    def complete(self, system: str, content: list[dict], timeout: float | None = None,
                 thinking: str | None = None, max_tokens: int | None = None) -> str:
        """`thinking` (off | on | low | medium | high) and `max_tokens` override the settings for this call only."""
        raise NotImplementedError


class OpenAICompatLLM(LLM):
    """Any OpenAI-compatible chat endpoint. Reads OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL.

    FORGE_LLM_TIMEOUT_S (300)   longest a single call may take; a call also never outlives `timeout`
    FORGE_MAX_TOKENS (6000)     reply limit
    FORGE_THINKING (off)        off = no thinking (vLLM / Qwen chat-template switch); on = server default
    FORGE_REASONING_EFFORT      passed through as reasoning_effort when set (and thinking is on)
    FORGE_TEMPERATURE, FORGE_SEED  sampling, for repeatable runs
    complete(..., thinking=, max_tokens=) override thinking and the reply limit for one call
    (the exact-program path thinks while the body path does not).
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

    def _extra(self, thinking: str | None) -> dict:
        """Request extras for one call; `thinking` None keeps the FORGE_THINKING setting."""
        if thinking is None:
            return self.extra
        extra = {k: v for k, v in self.extra.items() if k not in ("extra_body", "reasoning_effort")}
        if thinking in ("off", "0", "false", "no"):
            extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        elif thinking in ("low", "medium", "high"):
            extra["reasoning_effort"] = thinking
        return extra

    def complete(self, system: str, content: list[dict], timeout: float | None = None,
                 thinking: str | None = None, max_tokens: int | None = None) -> str:
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append({"type": "text", "text": block["text"]})
            else:
                parts.append({"type": "image_url",
                              "image_url": {"url": "data:image/png;base64," + block["data"]}})
        reply = self._create_retrying(
            model=self.model,
            max_tokens=max_tokens or self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": parts}],
            budget=max(5.0, min(self.timeout, timeout)) if timeout else self.timeout,
            **self._extra(thinking),
        )
        choice = reply.choices[0]
        self.calls += 1
        self.tokens += getattr(reply.usage, "completion_tokens", 0) or 0
        if choice.finish_reason == "length":
            print(f"llm: reply cut off at FORGE_MAX_TOKENS={self.max_tokens} "
                  f"({len(choice.message.content or '')} chars of answer)", file=sys.stderr, flush=True)
        return choice.message.content or ""


    def _create_retrying(self, budget: float, **kw):
        """One chat call. A connection that cannot be made (refused, reset, a quick timeout, 502/503/504)
        is retried with backoff for up to FORGE_LLM_RETRY_S (180) seconds, never past `budget`:
        a tunnel that drops for a minute must not turn a run into a no-model run."""
        import openai

        t0 = time.monotonic()
        retry_s = float(os.environ.get("FORGE_LLM_RETRY_S", "180"))
        wait, tries = 2.0, 0
        while True:
            left = budget - (time.monotonic() - t0)
            t_call = time.monotonic()
            try:
                return self.client.chat.completions.create(timeout=max(5.0, left), **kw)
            except (openai.APIConnectionError, openai.InternalServerError) as exc:
                status = getattr(exc, "status_code", None)
                quick = time.monotonic() - t_call < 30          # a read timeout on a long reply is not retried
                if isinstance(exc, openai.InternalServerError) and status not in (502, 503, 504):
                    raise
                if isinstance(exc, openai.APITimeoutError) and not quick:
                    raise
                spent = time.monotonic() - t0
                if spent + wait > min(retry_s, budget - 5):
                    raise
                tries += 1
                print(f"llm: {type(exc).__name__}{f' {status}' if status else ''}; retry {tries} in {wait:.0f}s "
                      f"({spent:.0f}s spent)", file=sys.stderr, flush=True)
                time.sleep(wait)
                wait = min(wait * 2, 30.0)


class ScriptedLLM(LLM):
    """Offline stand-in for tests: returns canned replies in order (last one repeats)."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, content: list[dict], timeout: float | None = None, **_) -> str:
        self.calls.append((system, content))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
