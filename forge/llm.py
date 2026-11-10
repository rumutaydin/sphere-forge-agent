"""Model access behind one small interface, so the agent can be pointed at
whatever models the hackathon provides by adding a class here.

Content is a list of blocks: {"type": "text", "text": ...} or image_block(path).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def image_block(path: str | Path) -> dict:
    path = Path(path)
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media[path.suffix.lower()], "data": data}}


class LLM:
    def complete(self, system: str, content: list[dict], effort: str = "medium") -> str:
        raise NotImplementedError


class AnthropicLLM(LLM):
    """Claude via the Anthropic SDK. Reads ANTHROPIC_API_KEY from the environment."""

    def __init__(self, model: str | None = None):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("FORGE_MODEL", "claude-opus-5-5")

    def complete(self, system: str, content: list[dict], effort: str = "medium") -> str:
        # Streaming keeps long generations clear of HTTP timeouts. `fallbacks` lets the
        # API re-run a declined request on another model inside the same call.
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=32000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            raise RuntimeError("model declined the request")
        return "".join(b.text for b in message.content if b.type == "text")


class ScriptedLLM(LLM):
    """Offline stand-in for tests: returns canned replies in order (last one repeats)."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, content: list[dict], effort: str = "medium") -> str:
        self.calls.append((system, content))
        return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
