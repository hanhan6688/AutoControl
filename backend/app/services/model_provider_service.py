"""Model provider configuration and adapters for AI roles."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import Protocol
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from openai import OpenAI

from app.config import settings


@dataclass(frozen=True)
class ModelProviderPreset:
    id: str
    name: str
    provider_type: str
    base_url: str
    default_model: str
    api_key_label: str
    note: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ModelProviderConfig:
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 30.0
    temperature: float = 0.1
    max_tokens: int = 700

    @property
    def api_key_masked(self) -> str:
        return mask_secret(self.api_key)

    @property
    def configured(self) -> bool:
        if self.provider.strip().lower() == "claude_code":
            return bool(self.enabled and self.api_key and self.api_key != "EMPTY")
        return bool(self.enabled and self.base_url and self.model and self.api_key and self.api_key != "EMPTY")

    def public_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_masked": self.api_key_masked,
            "timeout_seconds": self.timeout_seconds,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "configured": self.configured,
        }


class ChatClient(Protocol):
    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
    ) -> str:
        ...


def mask_secret(value: str | None) -> str:
    if not value or value == "EMPTY":
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}******{value[-2:]}"


class OpenAICompatibleClient:
    def __init__(self, config: ModelProviderConfig) -> None:
        self.config = config

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
    ) -> str:
        client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        return response.choices[0].message.content or ""


class AnthropicCompatibleClient:
    def __init__(self, config: ModelProviderConfig) -> None:
        self.config = config

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
    ) -> str:
        system_parts = [item["content"] for item in messages if item.get("role") == "system"]
        user_messages = [
            {"role": item.get("role", "user"), "content": item.get("content", "")}
            for item in messages
            if item.get("role") != "system"
        ]
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)

        endpoint = self.config.base_url.rstrip("/")
        if not endpoint.endswith("/messages"):
            endpoint = f"{endpoint}/v1/messages"
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Anthropic-compatible provider returned {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Anthropic-compatible provider request failed: {exc}") from exc

        content = data.get("content") or []
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        return str(content)


class MiniMaxAutoClient:
    """Try MiniMax OpenAI-compatible first, then Anthropic-compatible as fallback."""

    openai_base_url = "https://api.minimaxi.com/v1"
    anthropic_base_url = "https://api.minimaxi.com/anthropic"

    def __init__(self, config: ModelProviderConfig) -> None:
        self.config = config

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
    ) -> str:
        candidates = self._candidates()
        errors: list[str] = []
        for provider, base_url in candidates:
            client_config = replace(self.config, provider=provider, base_url=base_url)
            client: ChatClient
            if provider == "anthropic_compatible":
                client = AnthropicCompatibleClient(client_config)
            else:
                client = OpenAICompatibleClient(client_config)
            try:
                return client.complete(
                    messages=messages,
                    model=model,
                    timeout_seconds=timeout_seconds,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                errors.append(f"{provider} {base_url}: {exc}")
        raise RuntimeError("MiniMax auto provider failed: " + " | ".join(errors))

    def _candidates(self) -> list[tuple[str, str]]:
        base_url = self.config.base_url.rstrip("/") or self.openai_base_url
        if "anthropic" in base_url:
            return [
                ("anthropic_compatible", base_url),
                ("openai_compatible", self.openai_base_url),
            ]
        return [
            ("openai_compatible", base_url),
            ("anthropic_compatible", self.anthropic_base_url),
        ]


class ModelProviderService:
    def provider_presets(self) -> list[ModelProviderPreset]:
        return [
            ModelProviderPreset(
                id="claude-code",
                name="Claude Code (CLI)",
                provider_type="claude_code",
                base_url="",
                default_model="sonnet",
                api_key_label="Anthropic API Key",
                note="通过 Claude Code CLI 调用，需要本地安装 claude 命令和 ANTHROPIC_API_KEY。",
            ),
            ModelProviderPreset(
                id="minimax-auto",
                name="MiniMax M2.7 自动",
                provider_type="minimax_auto",
                base_url="https://api.minimaxi.com/v1",
                default_model="MiniMax-M2.7",
                api_key_label="MiniMax API Key",
                note="默认用于 PC Agent，优先 /v1，失败后自动尝试 /anthropic。",
            ),
            ModelProviderPreset(
                id="zhipu-glm",
                name="智谱 GLM",
                provider_type="openai_compatible",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                default_model="GLM-4.7-Flash",
                api_key_label="Zhipu API Key",
                note="推荐先用于 PC Agent，OpenAI 兼容接口。",
            ),
            ModelProviderPreset(
                id="minimax-openai",
                name="MiniMax OpenAI 兼容",
                provider_type="openai_compatible",
                base_url="https://api.minimaxi.com/v1",
                default_model="MiniMax-M2.7",
                api_key_label="MiniMax API Key",
                note="使用 MiniMax /v1 OpenAI 兼容接口。",
            ),
            ModelProviderPreset(
                id="minimax-anthropic",
                name="MiniMax Anthropic 兼容",
                provider_type="anthropic_compatible",
                base_url="https://api.minimaxi.com/anthropic",
                default_model="MiniMax-M2.7",
                api_key_label="MiniMax API Key",
                note="使用 Anthropic Messages 兼容接口。",
            ),
            ModelProviderPreset(
                id="deepseek",
                name="DeepSeek",
                provider_type="openai_compatible",
                base_url="https://api.deepseek.com",
                default_model="deepseek-chat",
                api_key_label="DeepSeek API Key",
                note="模型名可按实际账号权限调整。",
            ),
            ModelProviderPreset(
                id="qwen",
                name="通义千问 OpenAI 兼容",
                provider_type="openai_compatible",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                default_model="qwen-plus",
                api_key_label="DashScope API Key",
                note="DashScope OpenAI 兼容模式。",
            ),
            ModelProviderPreset(
                id="moonshot",
                name="Moonshot / Kimi",
                provider_type="openai_compatible",
                base_url="https://api.moonshot.cn/v1",
                default_model="moonshot-v1-8k",
                api_key_label="Moonshot API Key",
                note="适合中文 Web 页面理解。",
            ),
            ModelProviderPreset(
                id="custom-openai",
                name="本地 vLLM / OneAPI / LiteLLM",
                provider_type="custom_openai",
                base_url="http://127.0.0.1:8000/v1",
                default_model="local-model",
                api_key_label="API Key",
                note="自定义 OpenAI 兼容网关。",
            ),
        ]

    def pc_agent_config(self) -> ModelProviderConfig:
        return ModelProviderConfig(
            enabled=bool(settings.pc_agent_enabled),
            provider=(settings.pc_agent_provider or "minimax_auto").strip(),
            base_url=(settings.pc_agent_base_url or "").strip(),
            model=(settings.pc_agent_model or "").strip(),
            api_key=(settings.pc_agent_api_key or "").strip(),
            timeout_seconds=float(settings.pc_agent_timeout_seconds),
            temperature=float(settings.pc_agent_temperature),
            max_tokens=int(settings.pc_agent_max_tokens),
        )

    def apply_runtime_pc_agent_config(self, payload: dict[str, object]) -> ModelProviderConfig:
        config = self.pc_agent_config_from_payload(payload)
        settings.pc_agent_enabled = config.enabled
        settings.pc_agent_provider = config.provider
        settings.pc_agent_base_url = config.base_url
        settings.pc_agent_model = config.model
        settings.pc_agent_api_key = config.api_key
        settings.pc_agent_timeout_seconds = config.timeout_seconds
        settings.pc_agent_temperature = config.temperature
        settings.pc_agent_max_tokens = config.max_tokens
        return self.pc_agent_config()

    def pc_agent_config_from_payload(self, payload: dict[str, object]) -> ModelProviderConfig:
        current = self.pc_agent_config()
        api_key = str(payload.get("api_key") or "").strip() or current.api_key
        return ModelProviderConfig(
            enabled=bool(payload.get("enabled", current.enabled)),
            provider=str(payload.get("provider") or current.provider).strip(),
            base_url=str(payload.get("base_url") or current.base_url).strip(),
            model=str(payload.get("model") or current.model).strip(),
            api_key=api_key,
            timeout_seconds=float(payload.get("timeout_seconds") or current.timeout_seconds),
            temperature=float(payload.get("temperature") if payload.get("temperature") is not None else current.temperature),
            max_tokens=int(payload.get("max_tokens") or current.max_tokens),
        )

    def create_client(self, config: ModelProviderConfig | None = None) -> ChatClient:
        item = config or self.pc_agent_config()
        provider = item.provider.strip().lower()
        if provider == "minimax_auto":
            return MiniMaxAutoClient(item)
        if provider == "anthropic_compatible":
            return AnthropicCompatibleClient(item)
        if provider in {"openai_compatible", "custom_openai"}:
            return OpenAICompatibleClient(item)
        if provider == "claude_code":
            # Claude Code 走 CLI，不需要真正的 ChatClient，返回占位
            return OpenAICompatibleClient(item)
        raise ValueError(f"unsupported model provider: {item.provider}")
