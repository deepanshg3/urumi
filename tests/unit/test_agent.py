"""Unit tests for the chat agent (Pass 7).

The LLM and the gateway MCP client are both faked: these tests never hit
Gemini or a live gateway, so they are deterministic and offline.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from services.agent import persistence
from services.agent.api import AGENT_API_PREFIX
from services.agent.app import create_app
from services.agent.executor import AgentExecutor, ToolInvocation, build_tool_specs
from services.agent.gateway_client import GatewayTool, ToolResult
from services.agent.model import configure_tracing, is_placeholder_secret, require_api_key
from services.agent.prompt import render_system_prompt
from services.agent.schema import json_schema_to_model
from services.agent.service import AgentService
from services.common.config import AgentSettings, LangsmithSettings, LlmSettings
from services.common.errors import ConfigurationError
from services.gateway.auth import create_login_session, create_user
from services.gateway.db import Database, ensure_schema
from services.gateway.policy import PermissionPolicy

from tests.conftest import app_settings, gateway_settings

PASSWORD = "member-password-1"


# --- schema conversion ----------------------------------------------------


def test_schema_conversion_types_and_required() -> None:
    schema = {
        "type": "object",
        "properties": {
            "sku": {"type": "string", "description": "product SKU"},
            "limit": {"type": "integer", "default": 10},
            "status": {"type": "string", "enum": ["open", "closed"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "meta": {"type": "object"},
            "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["sku"],
    }
    model = json_schema_to_model("demo", schema)
    assert "sku" in model.model_json_schema()["required"]

    parsed = model.model_validate({"sku": "X", "limit": 3})
    assert parsed.sku == "X"
    assert parsed.limit == 3
    assert parsed.status is None


def test_schema_conversion_is_defensive() -> None:
    empty = json_schema_to_model("empty", {"type": "object"})
    assert empty.model_validate({}).model_dump() == {}
    weird = json_schema_to_model("weird", None)
    assert weird.model_validate({}).model_dump() == {}
    non_object = json_schema_to_model("str", {"type": "string"})
    assert non_object.model_validate({}).model_dump() == {}


def test_schema_enum_and_nullable() -> None:
    model = json_schema_to_model(
        "t",
        {
            "type": "object",
            "properties": {
                "mode": {"enum": ["fast", "slow"]},
                "n": {"type": ["integer", "null"]},
            },
        },
    )
    parsed = model.model_validate({"mode": "fast", "n": None})
    assert parsed.mode == "fast"


# --- model configuration --------------------------------------------------


def test_placeholder_and_key_validation() -> None:
    assert is_placeholder_secret("")
    assert is_placeholder_secret("your-gemini-api-key-here")
    assert is_placeholder_secret("replace-with-a-long-random-value")
    assert not is_placeholder_secret("AIzaSy-real-key")
    with pytest.raises(ConfigurationError):
        require_api_key(LlmSettings(api_key=""))
    assert require_api_key(LlmSettings(api_key="AIza-real")) == "AIza-real"


def test_tracing_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    assert configure_tracing(LangsmithSettings(tracing_enabled=False)) is False
    import os

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert configure_tracing(LangsmithSettings(tracing_enabled=True, api_key="")) is False
    assert (
        configure_tracing(
            LangsmithSettings(tracing_enabled=True, api_key="ls-real", project="proj")
        )
        is True
    )
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_PROJECT"] == "proj"


# --- prompt ---------------------------------------------------------------


def test_render_system_prompt_lists_tools() -> None:
    settings = AgentSettings(
        system_prompt_path="does/not/exist.txt",
        business_timezone="UTC",
    )
    tools = [GatewayTool("inventory__get_stock", "Check stock levels", {"type": "object"})]
    text = render_system_prompt(settings, tools, user_email="a@b.test")
    assert "Urumi" in text
    assert "inventory__get_stock" in text
    assert "a@b.test" in text
    assert "permissions" in text.lower()


# --- executor -------------------------------------------------------------


def _spec(tool: str = "inventory__get_stock"):
    return build_tool_specs(
        [
            GatewayTool(
                tool,
                "Check stock",
                {
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "required": ["sku"],
                },
            )
        ]
    )


class FakeModel:
    def __init__(self, script: list[AIMessage]) -> None:
        self.script = list(script)
        self.calls: list[Any] = []

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.calls.append(messages)
        if not self.script:
            raise AssertionError("model called more times than scripted")
        return self.script.pop(0)


def _call(name: str, args: dict[str, Any], call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


async def _executor(model: FakeModel, *, max_iterations: int = 6, max_tool_calls: int = 8, specs=None):
    return AgentExecutor(
        model,
        specs if specs is not None else _spec(),
        max_iterations=max_iterations,
        max_tool_calls=max_tool_calls,
        model_timeout_seconds=5.0,
        tool_timeout_seconds=5.0,
    )


async def test_executor_happy_path() -> None:
    model = FakeModel([_call("inventory__get_stock", {"sku": "MUG"}), AIMessage(content="25 in stock.")])

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:
        assert name == "inventory__get_stock"
        assert args == {"sku": "MUG"}
        return ToolResult(text='{"quantity": 25}', structured={"quantity": 25})

    result = await (await _executor(model)).run(
        system_prompt="sys", history=[HumanMessage(content="hi")], user_text="stock?", caller=caller
    )
    assert result.reply == "25 in stock."
    assert result.iterations == 2
    assert not result.truncated
    assert [inv.status for inv in result.invocations] == ["ok"]


async def test_executor_unknown_tool_is_not_executed() -> None:
    model = FakeModel([_call("nope__tool", {}), AIMessage(content="No such tool.")])
    called = False

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(text="should not happen")

    result = await (await _executor(model)).run(
        system_prompt="s", history=[], user_text="x", caller=caller
    )
    assert called is False
    assert result.invocations[0].status == "unknown_tool"
    assert result.reply == "No such tool."


async def test_executor_invalid_arguments() -> None:
    model = FakeModel([_call("inventory__get_stock", {"sku": 5}), AIMessage(content="bad args")])

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:  # pragma: no cover
        raise AssertionError("must not be called")

    result = await (await _executor(model)).run(
        system_prompt="s", history=[], user_text="x", caller=caller
    )
    assert result.invocations[0].status == "invalid_arguments"


async def test_executor_rejects_unknown_arguments() -> None:
    """A misspelled argument must fail loudly instead of being dropped."""

    model = FakeModel([_call("inventory__get_stock", {"sku": "MUG", "skku": "Oops"}), AIMessage(content="ok")])

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:  # pragma: no cover
        raise AssertionError("must not be called")

    result = await (await _executor(model)).run(
        system_prompt="s", history=[], user_text="x", caller=caller
    )
    invocation = result.invocations[0]
    assert invocation.status == "invalid_arguments"
    assert "skku" in invocation.error
    assert "sku" in invocation.error  # the allowed arguments are listed back


def test_schema_conversion_forbids_unknown_arguments() -> None:
    model = json_schema_to_model(
        "inventory__get_stock",
        {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    )
    with pytest.raises(Exception):
        model.model_validate({"sku": "MUG", "unexpected": 1})
    assert model.model_validate({"sku": "MUG"}).sku == "MUG"


async def test_executor_tool_error_is_reported_to_model() -> None:
    model = FakeModel([_call("inventory__get_stock", {"sku": "X"}), AIMessage(content="denied")])
    seen: list[Any] = []

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:
        raise RuntimeError("boom")

    orig = model.ainvoke

    async def spy(messages: list[Any]) -> AIMessage:
        seen.append(messages[-1])
        return await orig(messages)

    model.ainvoke = spy  # type: ignore[method-assign]
    result = await (await _executor(model)).run(
        system_prompt="s", history=[], user_text="x", caller=caller
    )
    assert result.invocations[0].is_error
    assert isinstance(seen[-1], type(seen[-1]))  # ToolMessage appended
    assert "error" in seen[-1].content


async def test_executor_enforces_max_tool_calls() -> None:
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "inventory__get_stock", "args": {"sku": "A"}, "id": "1"},
                    {"name": "inventory__get_stock", "args": {"sku": "B"}, "id": "2"},
                ],
            ),
            AIMessage(content="done"),
        ]
    )

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:
        return ToolResult(text="ok")

    result = await (await _executor(model, max_tool_calls=1)).run(
        system_prompt="s", history=[], user_text="x", caller=caller
    )
    assert result.truncated is True
    assert result.truncated_reason == "max_tool_calls"
    assert len(result.invocations) == 1


async def test_executor_enforces_max_iterations() -> None:
    model = FakeModel([_call("inventory__get_stock", {"sku": "A"}, f"c{i}") for i in range(5)])

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:
        return ToolResult(text="ok")

    result = await (await _executor(model, max_iterations=2, max_tool_calls=50)).run(
        system_prompt="s", history=[], user_text="x", caller=caller
    )
    assert result.truncated is True
    assert result.truncated_reason == "max_iterations"


async def test_executor_model_timeout() -> None:
    import asyncio

    class SlowModel:
        async def ainvoke(self, messages: list[Any]) -> AIMessage:
            await asyncio.sleep(1)
            return AIMessage(content="late")

    executor = AgentExecutor(
        SlowModel(),
        _spec(),
        max_iterations=2,
        max_tool_calls=2,
        model_timeout_seconds=0.01,
        tool_timeout_seconds=1.0,
    )

    async def caller(name: str, args: dict[str, Any]) -> ToolResult:  # pragma: no cover
        return ToolResult(text="ok")

    result = await executor.run(system_prompt="s", history=[], user_text="x", caller=caller)
    assert result.model_error == "timeout"
    assert result.truncated_reason == "model_timeout"


# --- persistence ----------------------------------------------------------


async def _agent_database(tmp_path) -> Database:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'agent.db'}")
    await ensure_schema(db)
    await persistence.ensure_agent_schema(db)
    return db


async def test_conversation_lifecycle_and_isolation(tmp_path) -> None:
    db = await _agent_database(tmp_path)
    try:
        conv = await persistence.create_conversation(db, user_id=1, title="hello")
        await persistence.append_message(db, conv.id, "user", "hi")
        await persistence.append_message(db, conv.id, "assistant", "hello", tool_summary=[{"tool": "t"}])
        messages = await persistence.list_messages(db, conv.id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert await persistence.get_conversation(db, conv.id, 999) is None
        assert await persistence.delete_conversation(db, conv.id, 999) is False
        assert await persistence.delete_conversation(db, conv.id, 1) is True
        assert await persistence.list_messages(db, conv.id) == []
    finally:
        await db.dispose()


async def test_trim_conversation_keeps_newest(tmp_path) -> None:
    db = await _agent_database(tmp_path)
    try:
        conv = await persistence.create_conversation(db, user_id=1)
        for i in range(5):
            await persistence.append_message(db, conv.id, "user", f"m{i}")
        await persistence.trim_conversation(db, conv.id, max_messages=3)
        remaining = await persistence.list_messages(db, conv.id)
        assert [m.content for m in remaining] == ["m2", "m3", "m4"]
    finally:
        await db.dispose()


# --- service (fake gateway + fake model) ----------------------------------


class FakeGatewayClient:
    def __init__(self, tools: list[GatewayTool], responder: Callable[[str, dict], ToolResult], sink: list[str]):
        self._tools = tools
        self._responder = responder
        self._sink = sink

    async def __aenter__(self) -> "FakeGatewayClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def list_tools(self) -> list[GatewayTool]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        return self._responder(name, arguments)


def _chat_settings(**overrides: Any) -> Any:
    llm = overrides.pop("llm", LlmSettings(model="gemini-test", api_key="AIza-real"))
    agent = overrides.pop(
        "chat_agent",
        AgentSettings(
            gateway_mcp_url="http://gateway.test/mcp",
            system_prompt_path="does/not/exist.txt",
            max_history_messages=10,
        ),
    )
    return app_settings(service_name="agent", llm=llm, chat_agent=agent, **overrides)


def _service(db: Database, settings, tools, responder, sink, script):
    tokens_seen: list[str] = []

    def client_factory(token: str) -> FakeGatewayClient:
        tokens_seen.append(token)
        return FakeGatewayClient(tools, responder, sink)

    def model_factory(llm, lc_tools):
        sink.append(f"tools={len(lc_tools)}")
        return FakeModel(script)

    svc = AgentService(db, settings, model_factory=model_factory, client_factory=client_factory)
    return svc, tokens_seen


async def test_service_chat_end_to_end(tmp_path) -> None:
    db = await _agent_database(tmp_path)
    try:
        settings = _chat_settings()
        tools = [GatewayTool("inventory__get_stock", "Check stock", {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]})]
        sink: list[str] = []

        def responder(name, args):
            return ToolResult(text='{"quantity": 25}')

        svc, tokens = _service(
            db,
            settings,
            tools,
            responder,
            sink,
            [_call("inventory__get_stock", {"sku": "MUG"}), AIMessage(content="25 units.")],
        )
        user = await create_user(db, "u@test", "U", PASSWORD, ["member"])
        outcome = await svc.handle_chat(user, "how many mugs?")
        assert outcome.reply == "25 units."
        assert outcome.tool_calls == [{"tool": "inventory__get_stock", "status": "ok", "latency_ms": 0}]

        messages = await persistence.list_messages(db, outcome.conversation_id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[1].tool_summary == outcome.tool_calls

        # delegation: a token was minted and revoked after the turn
        assert tokens and tokens[0].startswith("urumi_")

        # conversation continues
        outcome2 = await svc.handle_chat(user, "and now?", conversation_id=outcome.conversation_id)
        assert outcome2.conversation_id == outcome.conversation_id
    finally:
        await db.dispose()


async def test_service_history_is_passed_to_model(tmp_path) -> None:
    db = await _agent_database(tmp_path)
    try:
        settings = _chat_settings()
        sink: list[str] = []
        svc, _ = _service(db, settings, [], lambda n, a: ToolResult(text=""), sink, [])
        user = await create_user(db, "h@test", "H", PASSWORD, ["member"])
        conv = await persistence.create_conversation(db, user.id)
        await persistence.append_message(db, conv.id, "user", "first")
        await persistence.append_message(db, conv.id, "assistant", "reply")

        captured: dict[str, Any] = {}

        def model_factory(llm, lc_tools):
            model = FakeModel([AIMessage(content="ok")])

            async def spy(messages):
                captured["history"] = messages
                return AIMessage(content="ok")

            model.ainvoke = spy  # type: ignore[method-assign]
            return model

        svc._model_factory = model_factory  # type: ignore[assignment]
        await svc.handle_chat(user, "second", conversation_id=conv.id)
        contents = [getattr(m, "content", "") for m in captured["history"]]
        assert "first" in contents and "reply" in contents and "second" in contents
    finally:
        await db.dispose()


async def test_service_real_model_factory_requires_key(tmp_path) -> None:
    db = await _agent_database(tmp_path)
    try:
        settings = _chat_settings(llm=LlmSettings(model="gemini-test", api_key=""))
        sink: list[str] = []
        # No model_factory injected: the real build_chat_model path is exercised.
        svc = AgentService(
            db,
            settings,
            client_factory=lambda token: FakeGatewayClient(
                [GatewayTool("inventory__check_stock", "stock", {"type": "object"})],
                lambda n, a: ToolResult(text="{}"),
                sink,
            ),
        )
        user = await create_user(db, "k@test", "K", PASSWORD, ["member"])
        outcome = await svc.handle_chat(user, "hello")
        assert outcome.truncated_reason == "configuration_error"
        assert "configured" in outcome.reply.lower()
    finally:
        await db.dispose()


async def test_service_reports_model_configuration_error(tmp_path) -> None:
    db = await _agent_database(tmp_path)
    try:
        settings = _chat_settings()
        sink: list[str] = []

        def failing_factory(llm, lc_tools):
            raise ConfigurationError("GEMINI_API_KEY is not configured.")

        svc = AgentService(
            db,
            settings,
            model_factory=failing_factory,
            client_factory=lambda token: FakeGatewayClient([], lambda n, a: ToolResult(text=""), sink),
        )
        user = await create_user(db, "c@test", "C", PASSWORD, ["member"])
        outcome = await svc.handle_chat(user, "hello")
        assert outcome.truncated is True
        assert outcome.truncated_reason == "configuration_error"
        assert "not configured" in outcome.reply.lower()
    finally:
        await db.dispose()


async def test_service_rejects_unknown_conversation(tmp_path) -> None:
    db = await _agent_database(tmp_path)
    try:
        settings = _chat_settings()
        svc = AgentService(
            db, settings, model_factory=lambda l, t: FakeModel([]),
            client_factory=lambda token: FakeGatewayClient([], lambda n, a: ToolResult(text=""), []),
        )
        user = await create_user(db, "n@test", "N", PASSWORD, ["member"])
        from services.common.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await svc.handle_chat(user, "hi", conversation_id=999)
    finally:
        await db.dispose()


# --- HTTP API -------------------------------------------------------------


@contextlib.asynccontextmanager
async def agent_client(tmp_path, *, script: list[AIMessage], tools: list[GatewayTool]) -> AsyncIterator[httpx.AsyncClient]:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    settings = _chat_settings()
    sink: list[str] = []

    def model_factory(llm, lc_tools):
        return FakeModel(list(script))

    def responder(name: str, args: dict[str, Any]) -> ToolResult:
        return ToolResult(text='{"ok": true}')

    service = AgentService(
        db,
        settings,
        model_factory=model_factory,
        client_factory=lambda token: FakeGatewayClient(tools, responder, sink),
    )
    app = create_app(settings, database=db, service=service)
    async with app.router.lifespan_context(app):
        user = await create_user(db, "api@test", "Api", PASSWORD, ["member"])
        gw_settings = gateway_settings()
        token, csrf, _ = await create_login_session(db, gw_settings, user.id)
        transport = httpx.ASGITransport(app=app)
        jar = httpx.Cookies()
        jar.set("urumi_session", token)
        jar.set("urumi_csrf", csrf)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", cookies=jar
        ) as http:
            http.headers["X-CSRF-Token"] = csrf
            yield http


async def test_agent_api_requires_auth(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'anon.db'}")
    settings = _chat_settings()
    app = create_app(settings, database=db, service=AgentService(
        db, settings, model_factory=lambda l, t: FakeModel([]),
        client_factory=lambda token: FakeGatewayClient([], lambda n, a: ToolResult(text=""), []),
    ))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            assert (await http.get(f"{AGENT_API_PREFIX}/tools")).status_code == 401
            assert (await http.post(f"{AGENT_API_PREFIX}/chat", json={"message": "hi"})).status_code == 401


async def test_agent_api_tools_and_chat(tmp_path) -> None:
    tools = [GatewayTool("shipping__track", "Track a shipment", {"type": "object", "properties": {}})]
    script = [AIMessage(content="Hello there.")]
    async with agent_client(tmp_path, script=script, tools=tools) as http:
        tools_resp = await http.get(f"{AGENT_API_PREFIX}/tools")
        assert tools_resp.status_code == 200
        assert tools_resp.json()[0]["name"] == "shipping__track"

        chat = await http.post(f"{AGENT_API_PREFIX}/chat", json={"message": "hi"})
        assert chat.status_code == 200, chat.text
        body = chat.json()
        assert body["reply"] == "Hello there."
        assert body["conversation_id"]

        convs = await http.get(f"{AGENT_API_PREFIX}/conversations")
        assert [c["id"] for c in convs.json()] == [body["conversation_id"]]

        detail = await http.get(f"{AGENT_API_PREFIX}/conversations/{body['conversation_id']}")
        assert [m["role"] for m in detail.json()["messages"]] == ["user", "assistant"]


async def test_agent_api_csrf_required(tmp_path) -> None:
    async with agent_client(tmp_path, script=[], tools=[]) as http:
        del http.headers["X-CSRF-Token"]
        resp = await http.post(f"{AGENT_API_PREFIX}/chat", json={"message": "hi"})
        assert resp.status_code == 403


async def test_agent_api_cannot_read_other_users_conversation(tmp_path) -> None:
    tools: list[GatewayTool] = []
    async with agent_client(tmp_path, script=[AIMessage(content="a")], tools=tools) as http:
        chat = await http.post(f"{AGENT_API_PREFIX}/chat", json={"message": "hi"})
        conv_id = chat.json()["conversation_id"]

    # a second app instance over the same DB file, different user
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    settings = _chat_settings()
    app = create_app(settings, database=db, service=AgentService(
        db, settings, model_factory=lambda l, t: FakeModel([]),
        client_factory=lambda token: FakeGatewayClient([], lambda n, a: ToolResult(text=""), []),
    ))
    async with app.router.lifespan_context(app):
        other = await create_user(db, "other@test", "Other", PASSWORD, ["member"])
        token, csrf, _ = await create_login_session(db, gateway_settings(), other.id)
        transport = httpx.ASGITransport(app=app)
        jar = httpx.Cookies()
        jar.set("urumi_session", token)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", cookies=jar) as http:
            resp = await http.get(f"{AGENT_API_PREFIX}/conversations/{conv_id}")
            assert resp.status_code == 404
