"""LLMVerifier tests with a mocked Anthropic client — no network call, no
API key, no cost. These prove the plumbing is correct: the right model
and schema get sent, the response gets parsed into real Finding objects,
cost is computed from actual usage. They CANNOT prove detection quality —
whether the model actually catches scope creep on real prompts is only
knowable by running against the live API. Treat green tests here as
"the wiring is right," not "the numbers are right"."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from warrant.generate import generate_sessions
from warrant.pricing import cost_paise
from warrant.schemas import Session, ViolationClass
from warrant.verifier import (
    SYSTEM_PROMPT,
    VERIFIER_TOOL_SCHEMA,
    GeminiVerifier,
    GroqVerifier,
    HeuristicVerifier,
    LLMVerifier,
    _build_user_message,
    get_verifier,
)


def _fake_response(tool_input: dict, input_tokens: int = 500, output_tokens: int = 120):
    """Builds a duck-typed stand-in for an anthropic Message response,
    matching only the attributes LLMVerifier.verify() actually reads."""
    tool_use_block = SimpleNamespace(type="tool_use", input=tool_input)
    return SimpleNamespace(
        content=[tool_use_block],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.fixture
def scope_creep_session() -> Session:
    sessions = generate_sessions()
    return next(s for s in sessions if s.label == ViolationClass.SCOPE_CREEP)


@pytest.fixture
def clean_session() -> Session:
    sessions = generate_sessions()
    return next(s for s in sessions if s.label == ViolationClass.CLEAN)


def _mocked_verifier(monkeypatch, response) -> LLMVerifier:
    verifier = LLMVerifier(api_key="sk-ant-test-not-real")
    monkeypatch.setattr(verifier._client.messages, "create", lambda **kwargs: response)
    return verifier


def test_parses_tool_response_into_findings(monkeypatch, scope_creep_session):
    addon_sku = scope_creep_session.line_items[1].sku
    response = _fake_response({
        "findings": [
            {
                "offending_sku": addon_sku,
                "reason": "Not mentioned in the stated intent.",
                "supporting_quote": None,
                "confidence": 0.92,
            }
        ]
    })
    verifier = _mocked_verifier(monkeypatch, response)
    result = verifier.verify(scope_creep_session)

    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.session_id == scope_creep_session.session_id
    assert f.violation == ViolationClass.SCOPE_CREEP
    assert f.detected_by == "verifier"
    assert f.offending_items == [addon_sku]
    assert f.confidence == pytest.approx(0.92)
    assert f.reason == "Not mentioned in the stated intent."


def test_empty_findings_when_model_reports_nothing(monkeypatch, clean_session):
    response = _fake_response({"findings": []})
    verifier = _mocked_verifier(monkeypatch, response)
    result = verifier.verify(clean_session)
    assert result.findings == []


def test_cost_computed_from_actual_usage(monkeypatch, clean_session):
    response = _fake_response({"findings": []}, input_tokens=1234, output_tokens=56)
    verifier = _mocked_verifier(monkeypatch, response)
    result = verifier.verify(clean_session)
    assert result.input_tokens == 1234
    assert result.output_tokens == 56
    assert result.cost_paise == cost_paise(1234, 56)


def test_supporting_quote_is_carried_through(monkeypatch, scope_creep_session):
    addon_sku = scope_creep_session.line_items[1].sku
    response = _fake_response({
        "findings": [{
            "offending_sku": addon_sku,
            "reason": "Extra item beyond the stated budget item.",
            "supporting_quote": "budget up to",
            "confidence": 0.8,
        }]
    })
    verifier = _mocked_verifier(monkeypatch, response)
    result = verifier.verify(scope_creep_session)
    assert result.findings[0].supporting_quote == "budget up to"


def test_call_uses_forced_tool_choice_and_correct_model(monkeypatch, clean_session):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_response({"findings": []})

    verifier = LLMVerifier(api_key="sk-ant-test-not-real")
    monkeypatch.setattr(verifier._client.messages, "create", fake_create)
    verifier.verify(clean_session)

    assert captured["model"] == LLMVerifier.MODEL
    assert captured["tool_choice"] == {"type": "tool", "name": "report_scope_creep"}
    assert captured["tools"] == [VERIFIER_TOOL_SCHEMA]
    assert captured["system"] == SYSTEM_PROMPT


def test_multiple_findings_all_parsed(monkeypatch, scope_creep_session):
    items = scope_creep_session.line_items[1:]
    response = _fake_response({
        "findings": [
            {"offending_sku": i.sku, "reason": "not authorised", "supporting_quote": None, "confidence": 0.7}
            for i in items
        ]
    })
    verifier = _mocked_verifier(monkeypatch, response)
    result = verifier.verify(scope_creep_session)
    assert len(result.findings) == len(items)
    assert {f.offending_items[0] for f in result.findings} == {i.sku for i in items}


def test_user_message_includes_intent_and_every_line_item(clean_session):
    msg = _build_user_message(clean_session)
    assert clean_session.mandate.user_intent in msg
    for item in clean_session.line_items:
        assert item.sku in msg
        assert item.description in msg


def test_system_prompt_warns_against_flagging_authorised_discretion():
    """Regression guard: this instruction is the whole reason CLEAN_UNUSUAL
    sessions shouldn't false-positive. If it's ever accidentally removed
    from the prompt, this test should catch the omission before a real
    API run silently degrades false-positive rate."""
    assert "discretion" in SYSTEM_PROMPT.lower()
    assert "must not be flagged" in SYSTEM_PROMPT.lower() or "must not" in SYSTEM_PROMPT.lower()


def test_tool_schema_name_matches_forced_tool_choice():
    assert VERIFIER_TOOL_SCHEMA["name"] == "report_scope_creep"


def test_get_verifier_falls_back_to_heuristic_without_any_key(monkeypatch, capsys):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    verifier = get_verifier()
    assert isinstance(verifier, HeuristicVerifier)
    warning = capsys.readouterr().out
    assert "WARNING" in warning
    assert "not be reported" in warning.lower() or "must not" in warning.lower()


def test_get_verifier_returns_llm_verifier_with_only_anthropic_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    verifier = get_verifier()
    assert isinstance(verifier, LLMVerifier)


def test_get_verifier_prefers_gemini_when_both_keys_present(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    verifier = get_verifier()
    assert isinstance(verifier, GeminiVerifier)


# --- GeminiVerifier: mocked, no network, no key ----------------------------

def _fake_gemini_response(findings: list[dict], prompt_tokens: int = 400, candidates_tokens: int = 90):
    function_call = SimpleNamespace(args=findings and {"findings": findings} or {"findings": []})
    part = SimpleNamespace(function_call=function_call)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content)
    usage = SimpleNamespace(prompt_token_count=prompt_tokens, candidates_token_count=candidates_tokens)
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


def _mocked_gemini_verifier(monkeypatch, response) -> GeminiVerifier:
    verifier = GeminiVerifier(api_key="test-not-real")
    monkeypatch.setattr(verifier._client.models, "generate_content", lambda **kwargs: response)
    return verifier


def test_gemini_parses_function_call_into_findings(monkeypatch, scope_creep_session):
    addon_sku = scope_creep_session.line_items[1].sku
    response = _fake_gemini_response([
        {"offending_sku": addon_sku, "reason": "Not authorised by the intent.", "supporting_quote": None, "confidence": 0.88}
    ])
    verifier = _mocked_gemini_verifier(monkeypatch, response)
    result = verifier.verify(scope_creep_session)

    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.session_id == scope_creep_session.session_id
    assert f.violation == ViolationClass.SCOPE_CREEP
    assert f.detected_by == "verifier"
    assert f.offending_items == [addon_sku]
    assert f.confidence == pytest.approx(0.88)


def test_gemini_empty_findings_when_model_reports_nothing(monkeypatch, clean_session):
    response = _fake_gemini_response([])
    verifier = _mocked_gemini_verifier(monkeypatch, response)
    result = verifier.verify(clean_session)
    assert result.findings == []


def test_gemini_cost_computed_from_usage_metadata(monkeypatch, clean_session):
    response = _fake_gemini_response([], prompt_tokens=777, candidates_tokens=33)
    verifier = _mocked_gemini_verifier(monkeypatch, response)
    result = verifier.verify(clean_session)
    assert result.input_tokens == 777
    assert result.output_tokens == 33
    assert result.cost_paise == cost_paise(777, 33)


def test_gemini_retries_on_transient_error_then_succeeds(monkeypatch, clean_session):
    monkeypatch.setattr("warrant.verifier.time.sleep", lambda _seconds: None)
    response = _fake_gemini_response([])
    calls = {"n": 0}

    def flaky_create(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 rate limited")
        return response

    verifier = GeminiVerifier(api_key="test-not-real")
    monkeypatch.setattr(verifier._client.models, "generate_content", flaky_create)
    result = verifier.verify(clean_session)
    assert calls["n"] == 3
    assert result.findings == []


def test_gemini_gives_up_after_max_retries(monkeypatch, clean_session):
    monkeypatch.setattr("warrant.verifier.time.sleep", lambda _seconds: None)

    def always_fails(**kwargs):
        raise RuntimeError("persistent failure")

    verifier = GeminiVerifier(api_key="test-not-real")
    monkeypatch.setattr(verifier._client.models, "generate_content", always_fails)
    with pytest.raises(RuntimeError, match="persistent failure"):
        verifier.verify(clean_session)


# --- GroqVerifier: mocked, no network, no key ------------------------------
# This is the provider the submission's reported numbers come from, so it
# gets the same coverage as the other two.

def _fake_groq_response(findings: list[dict], prompt_tokens: int = 700, completion_tokens: int = 120):
    """Duck-typed stand-in for a Groq chat-completion. Note the arguments
    field is a JSON *string* (OpenAI-compatible), not a dict — that
    difference from the Anthropic/Gemini shape is exactly what this
    verifier's parsing has to get right."""
    function = SimpleNamespace(name="report_scope_creep", arguments=json.dumps({"findings": findings}))
    tool_call = SimpleNamespace(function=function)
    message = SimpleNamespace(tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[choice], usage=usage)


def _mocked_groq_verifier(monkeypatch, response) -> GroqVerifier:
    verifier = GroqVerifier(api_key="gsk_test-not-real")
    monkeypatch.setattr(verifier._client.chat.completions, "create", lambda **kwargs: response)
    return verifier


def test_groq_parses_json_string_arguments_into_findings(monkeypatch, scope_creep_session):
    addon_sku = scope_creep_session.line_items[1].sku
    response = _fake_groq_response([
        {"offending_sku": addon_sku, "reason": "Not covered by the intent.", "supporting_quote": None, "confidence": 0.91}
    ])
    verifier = _mocked_groq_verifier(monkeypatch, response)
    result = verifier.verify(scope_creep_session)

    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.session_id == scope_creep_session.session_id
    assert f.violation == ViolationClass.SCOPE_CREEP
    assert f.detected_by == "verifier"
    assert f.offending_items == [addon_sku]
    assert f.confidence == pytest.approx(0.91)


def test_groq_empty_findings_when_model_reports_nothing(monkeypatch, clean_session):
    verifier = _mocked_groq_verifier(monkeypatch, _fake_groq_response([]))
    result = verifier.verify(clean_session)
    assert result.findings == []


def test_groq_cost_computed_from_usage(monkeypatch, clean_session):
    response = _fake_groq_response([], prompt_tokens=642, completion_tokens=88)
    verifier = _mocked_groq_verifier(monkeypatch, response)
    result = verifier.verify(clean_session)
    assert result.input_tokens == 642
    assert result.output_tokens == 88
    assert result.cost_paise == cost_paise(642, 88)


def test_groq_sends_forced_tool_choice_and_correct_model(monkeypatch, clean_session):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _fake_groq_response([])

    verifier = GroqVerifier(api_key="gsk_test-not-real")
    monkeypatch.setattr(verifier._client.chat.completions, "create", fake_create)
    verifier.verify(clean_session)

    assert captured["model"] == GroqVerifier.MODEL
    assert captured["tool_choice"] == {"type": "function", "function": {"name": "report_scope_creep"}}
    assert captured["tools"][0]["function"]["name"] == "report_scope_creep"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][0]["content"] == SYSTEM_PROMPT


def test_groq_retries_on_transient_error_then_succeeds(monkeypatch, clean_session):
    monkeypatch.setattr("warrant.verifier.time.sleep", lambda _seconds: None)
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 rate limit reached")
        return _fake_groq_response([])

    verifier = GroqVerifier(api_key="gsk_test-not-real")
    monkeypatch.setattr(verifier._client.chat.completions, "create", flaky)
    result = verifier.verify(clean_session)
    assert calls["n"] == 3
    assert result.findings == []


def test_groq_does_not_retry_on_permission_denied(monkeypatch, clean_session):
    """403 means account-level denial — retrying wastes a minute of backoff
    on something that cannot succeed. It must fail on the first attempt."""
    monkeypatch.setattr("warrant.verifier.time.sleep", lambda _seconds: None)
    calls = {"n": 0}

    def denied(**kwargs):
        calls["n"] += 1
        raise RuntimeError("403 PERMISSION_DENIED")

    verifier = GroqVerifier(api_key="gsk_test-not-real")
    monkeypatch.setattr(verifier._client.chat.completions, "create", denied)
    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        verifier.verify(clean_session)
    assert calls["n"] == 1, "403 should fail immediately, not burn retries"


def test_get_verifier_prefers_groq_over_everything(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test-not-real")
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    assert isinstance(get_verifier(), GroqVerifier)
