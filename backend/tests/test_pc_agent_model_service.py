from __future__ import annotations


class FakeChatClient:
    def __init__(self) -> None:
        self.calls = []

    def complete(
        self,
        *,
        messages,
        model,
        timeout_seconds,
        temperature,
        max_tokens,
    ):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "timeout_seconds": timeout_seconds,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return '{"action":"click","target":"@e1","reason":"点击提交"}'


def test_pc_agent_model_service_uses_provider_client() -> None:
    from app.services.model_provider_service import ModelProviderConfig
    from app.services.pc_agent_model_service import PCAgentModelService

    client = FakeChatClient()
    config = ModelProviderConfig(
        enabled=True,
        provider="openai_compatible",
        base_url="https://example.test/v1",
        model="pc-model",
        api_key="secret",
        timeout_seconds=31,
        temperature=0.15,
        max_tokens=701,
    )
    service = PCAgentModelService(config_provider=lambda: config, client_factory=lambda item: client)

    decision = service.decide(
        {
            "task": "点击提交",
            "step": 1,
            "url": "https://example.test",
            "title": "Example",
            "elements": [{"ref": "@e1", "tag": "button", "text": "提交", "attrs": {}}],
            "history": [],
        }
    )

    assert decision["action"] == "click"
    assert decision["target"] == "@e1"
    assert client.calls[0]["model"] == "pc-model"
    assert client.calls[0]["timeout_seconds"] == 31


def test_pc_agent_model_service_returns_need_user_when_disabled() -> None:
    from app.services.model_provider_service import ModelProviderConfig
    from app.services.pc_agent_model_service import PCAgentModelService

    config = ModelProviderConfig(
        enabled=False,
        provider="openai_compatible",
        base_url="",
        model="",
        api_key="",
    )
    service = PCAgentModelService(config_provider=lambda: config)

    decision = service.decide({"task": "检查页面", "elements": []})

    assert decision["action"] == "need_user"
    assert "PC Agent AI 未启用" in decision["message"]


def test_pc_agent_model_service_returns_need_user_when_missing_key() -> None:
    from app.services.model_provider_service import ModelProviderConfig
    from app.services.pc_agent_model_service import PCAgentModelService

    config = ModelProviderConfig(
        enabled=True,
        provider="openai_compatible",
        base_url="https://example.test/v1",
        model="pc-model",
        api_key="EMPTY",
    )
    service = PCAgentModelService(config_provider=lambda: config)

    decision = service.decide({"task": "检查页面", "elements": []})

    assert decision["action"] == "need_user"
    assert "PC Agent AI 未配置" in decision["message"]
