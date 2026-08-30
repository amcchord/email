"""Provider registry, preference validation, and request-shape tests."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.routers.auth import _build_ai_preferences_response
from backend.schemas.auth import AIPreferencesUpdate
from backend.services.ai import AIService
from backend.services.chat import ChatService
from backend.services.ai_models import (
    ALLOWED_MODELS,
    DEFAULT_AI_PREFERENCES,
    MODELS_BY_PREFERENCE,
    provider_for_model,
)


def test_requested_model_families_are_registered():
    assert ALLOWED_MODELS == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "claude-fable-5",
        "claude-opus-5",
        "claude-sonnet-5",
    ]
    assert provider_for_model("gpt-5.6-sol") == "openai"
    assert provider_for_model("claude-opus-5") == "anthropic"


def test_smart_defaults_match_workload_cost_and_quality():
    assert DEFAULT_AI_PREFERENCES == {
        "chat_plan_model": "gpt-5.6-terra",
        "chat_plan_effort": "medium",
        "chat_execute_model": "gpt-5.6-luna",
        "chat_execute_effort": "low",
        "chat_verify_model": "gpt-5.6-sol",
        "chat_verify_effort": "high",
        "agentic_model": "gpt-5.6-luna",
        "agentic_effort": "low",
        "custom_prompt_model": "gpt-5.6-terra",
        "custom_prompt_effort": "medium",
        "unsubscribe_model": "claude-sonnet-5",
        "unsubscribe_effort": "medium",
    }


def test_unsubscribe_only_offers_computer_use_models():
    assert MODELS_BY_PREFERENCE["unsubscribe_model"] == [
        "claude-fable-5",
        "claude-opus-5",
        "claude-sonnet-5",
    ]


def test_preference_schema_rejects_incompatible_pairs():
    with pytest.raises(ValidationError, match="not supported for unsubscribe_model"):
        AIPreferencesUpdate(unsubscribe_model="gpt-5.6-luna")

    with pytest.raises(ValidationError, match="none effort is not supported"):
        AIPreferencesUpdate(
            agentic_model="claude-opus-5",
            agentic_effort="none",
        )


def test_response_retires_stale_models_and_normalizes_effort():
    response = _build_ai_preferences_response(
        {
            "agentic_model": "claude-sonnet-4-6",
            "agentic_effort": "max",
            "chat_plan_model": "claude-opus-5",
            "chat_plan_effort": "none",
        }
    )

    assert response.agentic_model == "gpt-5.6-luna"
    assert response.agentic_effort == "low"
    assert response.chat_plan_model == "claude-opus-5"
    assert response.chat_plan_effort == "high"


def test_chat_resolver_uses_defaults_for_retired_model_pair():
    user = SimpleNamespace(
        ai_preferences={
            "chat_plan_model": "claude-sonnet-4-6",
            "chat_plan_effort": "max",
        }
    )

    plan, execute, verify = ChatService()._get_models(user)

    assert plan == ("gpt-5.6-terra", "medium")
    assert execute == ("gpt-5.6-luna", "low")
    assert verify == ("gpt-5.6-sol", "high")


class _FakeResponses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _FakeOpenAI:
    def __init__(self, response):
        self.responses = _FakeResponses(response)


@pytest.mark.asyncio
async def test_openai_tool_call_uses_responses_api_and_effort():
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call",
                name="record_result",
                arguments='{"answer":"ok"}',
            )
        ],
        usage=SimpleNamespace(total_tokens=17),
    )
    fake = _FakeOpenAI(response)
    service = AIService(model="gpt-5.6-terra", effort="xhigh")
    service.openai_client = fake

    parsed, tokens = await service._call_claude_tool(
        model="gpt-5.6-terra",
        max_tokens=200,
        messages=[{"role": "user", "content": "test"}],
        tool={
            "name": "record_result",
            "description": "Record the result",
            "input_schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
        system="system",
    )

    assert parsed == {"answer": "ok"}
    assert tokens == 17
    assert fake.responses.kwargs["model"] == "gpt-5.6-terra"
    assert fake.responses.kwargs["reasoning"] == {"effort": "xhigh"}
    assert fake.responses.kwargs["store"] is False
    assert fake.responses.kwargs["tools"][0]["type"] == "function"
    assert fake.responses.kwargs["tool_choice"] == {
        "type": "function",
        "name": "record_result",
    }


class _FakeAnthropicMessages:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="record_result",
                    input={"answer": "ok"},
                )
            ],
            usage=SimpleNamespace(input_tokens=9, output_tokens=4),
        )


@pytest.mark.asyncio
async def test_anthropic_tool_call_uses_adaptive_effort():
    messages = _FakeAnthropicMessages()
    service = AIService(model="claude-opus-5", effort="max")
    service.client = SimpleNamespace(messages=messages)

    parsed, tokens = await service._call_claude_tool(
        model="claude-opus-5",
        max_tokens=200,
        messages=[{"role": "user", "content": "test"}],
        tool={"name": "record_result", "input_schema": {"type": "object"}},
    )

    assert parsed == {"answer": "ok"}
    assert tokens == 13
    assert messages.kwargs["model"] == "claude-opus-5"
    assert messages.kwargs["output_config"] == {"effort": "max"}
    assert "thinking" not in messages.kwargs
