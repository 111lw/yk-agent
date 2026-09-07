"""llm 层单测：全部走 Mock / stub，不发真实网络请求。"""

import json

import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from yk_agent.llm.factory import ProviderNotConfigured, get_provider
from yk_agent.llm.json_utils import SchemaValidationError, chat_validated
from yk_agent.llm.mock import MockLLMProvider
from yk_agent.llm.models import ChatMessage
from yk_agent.llm.provider import OpenAICompatibleProvider

# ---------- MockLLMProvider ----------


async def test_mock_chat_scripted_responses():
    mock = MockLLMProvider(["第一段", "第二段"])
    assert (await mock.chat([ChatMessage(role="user", content="hi")])).content == "第一段"
    assert (await mock.chat([ChatMessage(role="user", content="hi")])).content == "第二段"
    # 脚本耗尽 → 默认占位
    assert (await mock.chat([ChatMessage(role="user", content="hi")])).content == "（mock 回复）"
    assert len(mock.calls) == 3


async def test_mock_embed_dimension():
    mock = MockLLMProvider(embed_dim=8)
    vectors = await mock.embed(["a", "b"])
    assert len(vectors) == 2 and all(len(v) == 8 for v in vectors)


# ---------- OpenAICompatibleProvider ----------


def test_sampling_allowlist_rejects_unknown():
    with pytest.raises(ValueError, match="不支持的采样参数"):
        OpenAICompatibleProvider._filter_sampling({"temperture": 0.7})  # 拼写错误被拦截


def test_sampling_none_values_dropped():
    cleaned = OpenAICompatibleProvider._filter_sampling({"temperature": None, "top_p": 0.9})
    assert cleaned == {"top_p": 0.9}


class _StubCompletions:
    """记录入参、返回固定响应的 stub，替代 openai 客户端网络调用。"""

    def __init__(self, sink: dict):
        self._sink = sink

    async def create(self, **kwargs):
        self._sink.update(kwargs)
        return _fake_response(content='{"ok": true}')


def _fake_response(content: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        id="resp-1",
        model="mock-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


async def test_openai_provider_chat_json_mode():
    sink: dict = {}
    provider = OpenAICompatibleProvider(
        base_url="http://localhost",
        api_key="test",
        default_chat_model="test-model",
        default_embed_model="test-embed",
        client=AsyncOpenAI(base_url="http://localhost", api_key="test"),  # 不会真正发请求
    )
    provider._client.chat.completions = _StubCompletions(sink)

    result = await provider.chat(
        [ChatMessage(role="user", content="hi")], json_mode=True, temperature=0.2
    )
    assert result.content == '{"ok": true}'
    assert result.usage.total_tokens == 15
    assert sink["model"] == "test-model"
    assert sink["response_format"] == {"type": "json_object"}
    assert sink["temperature"] == 0.2


async def test_openai_provider_embed():
    from types import SimpleNamespace

    provider = OpenAICompatibleProvider(
        base_url="http://localhost",
        api_key="test",
        default_chat_model="m",
        default_embed_model="e",
        client=AsyncOpenAI(base_url="http://localhost", api_key="test"),
    )

    class _StubEmbeddings:
        async def create(self, *, model, input):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in input])

    provider._client.embeddings = _StubEmbeddings()
    assert await provider.embed(["x", "y"]) == [[0.1, 0.2], [0.1, 0.2]]
    assert await provider.embed([]) == []


# ---------- chat_validated ----------


class _Out(BaseModel):
    ok: bool


async def test_chat_validated_first_pass():
    mock = MockLLMProvider([json.dumps({"ok": True})])
    out = await chat_validated(mock, [ChatMessage(role="user", content="x")], _Out)
    assert out.ok is True


async def test_chat_validated_retry_then_success():
    mock = MockLLMProvider(["不是 JSON", json.dumps({"ok": False})])
    out = await chat_validated(mock, [ChatMessage(role="user", content="x")], _Out)
    assert out.ok is False
    # 第二次调用应携带重试提示
    second_call_messages = mock.calls[1]["messages"]
    assert any("Schema" in m.content or "校验" in m.content for m in second_call_messages)


async def test_chat_validated_gives_up_after_retry():
    mock = MockLLMProvider(["bad", "still bad"])
    with pytest.raises(SchemaValidationError):
        await chat_validated(mock, [ChatMessage(role="user", content="x")], _Out)
    assert len(mock.calls) == 2  # 恰好重试 1 次，不会无限循环


# ---------- factory ----------


def test_factory_raises_without_key(monkeypatch):
    from types import SimpleNamespace

    import yk_agent.llm.factory as factory

    monkeypatch.setattr(factory, "settings", SimpleNamespace(ark_api_key=""))
    get_provider.cache_clear()
    with pytest.raises(ProviderNotConfigured):
        get_provider()
    get_provider.cache_clear()  # 还原，避免影响其他用例
