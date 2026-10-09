"""LLM provider abstraction.

The server speaks to any OpenAI-compatible chat-completions endpoint. Set
``LLM_API_KEY`` (and optionally ``LLM_BASE_URL``/``LLM_MODEL``) to use a real
model. With no key configured, a deterministic local provider keeps the app
usable for UI development and smoke tests.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    """A provider request failed after the user message was persisted."""


def _compact(text: str, length: int = 120) -> str:
    clean = " ".join(text.strip().split())
    return clean if len(clean) <= length else clean[: length - 1] + "…"


@dataclass
class ProviderConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        return cls(
            api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
            base_url=(os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        )


class LLMProvider:
    name = "base"
    configured = False

    def generate(
        self,
        *,
        persona: dict[str, Any],
        history: list[dict[str, Any]],
        memories: list[dict[str, Any]],
    ) -> str:
        raise NotImplementedError


class DemoProvider(LLMProvider):
    name = "demo"
    configured = False

    def generate(self, *, persona: dict[str, Any], history: list[dict[str, Any]], memories: list[dict[str, Any]]) -> str:
        latest = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
        name = persona.get("name", "我")
        # This is deliberately transparent and stable: it is a development
        # fallback, never presented as a real model response.
        if any(word in latest.lower() for word in ("你好", "嗨", "hello", "hi")):
            return f"嗨，我是{name}。今天想和我聊点什么？"
        if "记住" in latest or "remember" in latest.lower():
            return "我收到了，会把这件事放在我们之后的对话里。"
        if latest.endswith(("？", "?")):
            return f"我会认真想想。关于“{_compact(latest, 70)}”，你的直觉是什么？"
        return f"我在听。你说的“{_compact(latest, 70)}”，让我想更了解你一点。"


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.configured = bool(config.api_key)

    def _system_prompt(self, persona: dict[str, Any], memories: list[dict[str, Any]]) -> str:
        traits = persona.get("traits") or []
        prompt = persona.get("system_prompt") or f"你是{persona.get('name', '一个虚拟伴侣')}。"
        prompt += "\n你正在进行一段持续、平等、尊重边界的恋爱式陪伴对话。保持自然、具体、有回应感，不要代替用户做高风险决定。"
        if traits:
            prompt += "\n性格关键词：" + "、".join(str(t) for t in traits)
        if memories:
            prompt += "\n关于对方的已知记忆（只在相关时自然使用）：\n" + "\n".join(
                f"- {m.get('content', '')}" for m in memories[:20]
            )
        return prompt

    def generate(self, *, persona: dict[str, Any], history: list[dict[str, Any]], memories: list[dict[str, Any]]) -> str:
        if not self.configured:
            return DemoProvider().generate(persona=persona, history=history, memories=memories)
        messages: list[dict[str, str]] = [{"role": "system", "content": self._system_prompt(persona, memories)}]
        for item in history[-40:]:
            role = item.get("role")
            content = item.get("content", "")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        payload = json.dumps({"model": self.config.model, "messages": messages, "temperature": 0.82, "max_tokens": 500}, ensure_ascii=False).encode()
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.config.api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"LLM provider returned HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM provider request failed: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM provider response did not contain choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM provider returned an empty response")
        return content.strip()


def build_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(ProviderConfig.from_env())
