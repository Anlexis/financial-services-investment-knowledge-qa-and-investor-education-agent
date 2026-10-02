# FIN-C2-111 — Unit Tests: release invariant at the output boundary
#
# This template renders no monetary aggregates of its own — the answer quotes
# the curated knowledge base (including statutory amounts) verbatim, so there
# is no numeric rounding grid to enforce. The invariant PostProcessNode owns:
#
#   1. Released answers are never empty.
#   2. Every released answer carries the mandated suitability disclaimer.
#   3. No credential material leaves the agent.
#
# Both directions are probed: every violation blocks the release, and clean
# disclaimed answers — including ones full of statutory yen amounts,
# percentages and decimals — pass byte-identically.
#
# The blocked contract is behavioural: the node returns an ERROR status and
# CLEARS both output-bearing state fields. Merely raising would not be
# fail-closed — the response envelope falls back to state["result"] even on
# an error status, so a blocked text left in state would still ship.

import pytest

from framework.schemas.agent_status import AgentStatus

from src.nodes.post_process_node import PostProcessNode
from src.nodes.suitability_gate_node import SUITABILITY_DISCLAIMER


@pytest.fixture(autouse=True)
def silence_audit(monkeypatch):
    monkeypatch.setattr("src.nodes.post_process_node.emit_trace_event", lambda *a, **k: None)


def _release(result_text):
    node = PostProcessNode()
    return node.execute({"result": result_text})


_CLEAN_ANSWERS = [
    "NISAは年間120万円まで非課税の制度です。",
    "年間投資枠が360万円（成長投資枠240万円＋積立投資枠120万円）に拡大されました。",
    "信託報酬は年率0.09572%、購入時手数料は1,234円です。",
    "基準価額 12,345.67 円の変動は元本割れリスクの一例です。",
]


class TestReleasePath:
    @pytest.mark.parametrize("answer", _CLEAN_ANSWERS)
    def test_disclaimed_answer_released_byte_identical(self, answer):
        """Clean disclaimed answers pass through unchanged — statutory
        amounts, percentages and decimals are never rewritten."""
        text = answer + SUITABILITY_DISCLAIMER
        result = _release(text)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["formatted_output"] == text


def _assert_blocked(result, *, never_echo=()):
    """The blocked contract: ERROR status, output fields cleared, rule named."""
    assert result["status"] == AgentStatus.ERROR.value
    # Both output-bearing fields are cleared so nothing can ship through the
    # envelope's result fallback.
    assert result["formatted_output"] == ""
    assert result["result"] == ""
    log_text = str(result.get("error_log", []))
    assert "output gate" in log_text
    for value in never_echo:
        assert str(value) not in log_text, f"blocked content echoed: {value!r}"


class TestBlockedPath:
    def test_empty_output_blocked(self):
        _assert_blocked(_release(""))

    def test_whitespace_only_output_blocked(self):
        _assert_blocked(_release("   \n  "))

    def test_missing_disclaimer_blocked(self):
        """An answer that lost its disclaimer must never be released —
        the boundary re-verifies what SuitabilityGateNode appended."""
        answer = "NISAは少額投資非課税制度です。"
        result = _release(answer)
        _assert_blocked(result, never_echo=[answer])
        assert "disclaimer missing" in str(result["error_log"])

    def test_partial_disclaimer_blocked(self):
        """A truncated disclaimer does not satisfy the invariant."""
        _assert_blocked(_release("答え。" + SUITABILITY_DISCLAIMER[:40]))

    @pytest.mark.parametrize(
        "credential",
        [
            "api_key=super_secret_12345",
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefgh",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
            "sk-abcdefghijklmnop1234",
            "AKIAIOSFODNN7EXAMPLE",
            "password: hunter2hunter2",
        ],
    )
    def test_each_credential_class_blocked(self, credential):
        """A credential riding in an otherwise valid answer blocks release —
        and the blocked text (credential included) is never echoed."""
        text = f"ご説明します。{credential} 以上です。" + SUITABILITY_DISCLAIMER
        _assert_blocked(_release(text), never_echo=[credential])

    def test_blocked_release_emits_audit_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(
            "src.nodes.post_process_node.emit_trace_event",
            lambda *a, **k: events.append(a),
        )
        _release("no disclaimer here")
        assert events and events[0][1]["outcome"] == "blocked"
