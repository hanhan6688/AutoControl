from __future__ import annotations


def test_pc_agent_config_uses_pc_agent_values(monkeypatch) -> None:
    from app.config import settings
    from app.services.model_provider_service import ModelProviderService

    monkeypatch.setattr(settings, "pc_agent_enabled", True)
    monkeypatch.setattr(settings, "pc_agent_provider", "openai_compatible")
    monkeypatch.setattr(settings, "pc_agent_base_url", "https://pc-agent.example/v1")
    monkeypatch.setattr(settings, "pc_agent_model", "pc-model")
    monkeypatch.setattr(settings, "pc_agent_api_key", "pc-secret")

    config = ModelProviderService().pc_agent_config()

    assert config.enabled is True
    assert config.provider == "openai_compatible"
    assert config.base_url == "https://pc-agent.example/v1"
    assert config.model == "pc-model"
    assert config.api_key == "pc-secret"
    assert config.api_key_masked == "pc******et"


def test_provider_presets_include_openai_and_anthropic_compatible() -> None:
    from app.services.model_provider_service import ModelProviderService

    presets = ModelProviderService().provider_presets()
    types = {preset.provider_type for preset in presets}
    ids = {preset.id for preset in presets}

    assert "openai_compatible" in types
    assert "anthropic_compatible" in types
    assert "minimax_auto" in types
    assert "minimax-auto" in ids
    assert "zhipu-glm" in ids
    assert "custom-openai" in ids


def test_apply_runtime_pc_agent_config_updates_settings_without_blank_key(monkeypatch) -> None:
    from app.config import settings
    from app.services.model_provider_service import ModelProviderService

    monkeypatch.setattr(settings, "pc_agent_api_key", "old-secret")

    config = ModelProviderService().apply_runtime_pc_agent_config(
        {
            "enabled": False,
            "provider": "custom_openai",
            "base_url": "http://127.0.0.1:8009/v1",
            "model": "local-model",
            "api_key": "",
            "timeout_seconds": 45,
            "temperature": 0.2,
            "max_tokens": 900,
        }
    )

    assert config.enabled is False
    assert config.provider == "custom_openai"
    assert config.base_url == "http://127.0.0.1:8009/v1"
    assert config.model == "local-model"
    assert config.api_key == "old-secret"
    assert config.timeout_seconds == 45
    assert config.temperature == 0.2
    assert config.max_tokens == 900


def test_pc_agent_config_from_payload_does_not_mutate_settings(monkeypatch) -> None:
    from app.config import settings
    from app.services.model_provider_service import ModelProviderService

    monkeypatch.setattr(settings, "pc_agent_provider", "openai_compatible")
    monkeypatch.setattr(settings, "pc_agent_base_url", "https://old.example/v1")
    monkeypatch.setattr(settings, "pc_agent_model", "old-model")
    monkeypatch.setattr(settings, "pc_agent_api_key", "old-secret")

    config = ModelProviderService().pc_agent_config_from_payload(
        {
            "provider": "anthropic_compatible",
            "base_url": "https://api.minimaxi.com/anthropic",
            "model": "MiniMax-M2.7",
            "api_key": "temporary-secret",
        }
    )

    assert config.provider == "anthropic_compatible"
    assert config.base_url == "https://api.minimaxi.com/anthropic"
    assert config.model == "MiniMax-M2.7"
    assert config.api_key == "temporary-secret"
    assert settings.pc_agent_provider == "openai_compatible"
    assert settings.pc_agent_api_key == "old-secret"


def test_minimax_auto_client_falls_back_to_anthropic(monkeypatch) -> None:
    from app.services import model_provider_service as module
    from app.services.model_provider_service import MiniMaxAutoClient, ModelProviderConfig

    calls = []

    class FakeOpenAIClient:
        def __init__(self, config):
            self.config = config

        def complete(self, **kwargs):
            calls.append((self.config.provider, self.config.base_url))
            raise RuntimeError("openai endpoint unavailable")

    class FakeAnthropicClient:
        def __init__(self, config):
            self.config = config

        def complete(self, **kwargs):
            calls.append((self.config.provider, self.config.base_url))
            return '{"action":"finish","message":"ok"}'

    monkeypatch.setattr(module, "OpenAICompatibleClient", FakeOpenAIClient)
    monkeypatch.setattr(module, "AnthropicCompatibleClient", FakeAnthropicClient)

    config = ModelProviderConfig(
        enabled=True,
        provider="minimax_auto",
        base_url="https://api.minimaxi.com/v1",
        model="MiniMax-M2.7",
        api_key="secret",
    )

    content = MiniMaxAutoClient(config).complete(
        messages=[],
        model=config.model,
        timeout_seconds=30,
        temperature=0.1,
        max_tokens=700,
    )

    assert content == '{"action":"finish","message":"ok"}'
    assert calls == [
        ("openai_compatible", "https://api.minimaxi.com/v1"),
        ("anthropic_compatible", "https://api.minimaxi.com/anthropic"),
    ]


def test_openai_compatible_client_disables_sdk_retries(monkeypatch) -> None:
    from app.services import model_provider_service as module
    from app.services.model_provider_service import ModelProviderConfig, OpenAICompatibleClient

    captured = {}

    class FakeChoice:
        message = type("Message", (), {"content": "{\"action\":\"finish\"}"})()

    class FakeCompletions:
        def create(self, **kwargs):
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(module, "OpenAI", FakeOpenAI)

    config = ModelProviderConfig(
        enabled=True,
        provider="openai_compatible",
        base_url="https://api.minimaxi.com/v1",
        model="MiniMax-M2.7",
        api_key="secret",
    )

    OpenAICompatibleClient(config).complete(
        messages=[],
        model=config.model,
        timeout_seconds=12,
        temperature=0.1,
        max_tokens=300,
    )

    assert captured["timeout"] == 12
    assert captured["max_retries"] == 0
