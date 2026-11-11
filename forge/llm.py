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
    def complete(self, system: str, content: list[dict]) -> str:
        raise NotImplementedError


class OpenAICompatLLM(LLM):
    """Any OpenAI-compatible chat endpoint. Reads OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL."""

    def __init__(self, model: str | None = None, timeout: float = 300.0):
        from openai import OpenAI

        self.client = OpenAI(timeout=timeout, max_retries=1)
        self.model = model or os.environ["OPENAI_MODEL"]
        self.max_tokens = int(os.environ.get("FORGE_MAX_TOKENS", "8000"))

    def complete(self, system: str, content: list[dict]) -> str:
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append({"type": "text", "text": block["text"]})
            else:
                parts.append({"type": "image_url",
                              "image_url": {"url": "data:image/png;base64," + block["data"]}})
        reply = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": parts}],
        )
        return reply.choices[0].message.content or ""


class ScriptedLLM(LLM):
    """Offline stand-in for tests: returns canned replies in order (last one repeats)."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, content: list[dict]) -> str:
        self.calls.append((system, content))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
