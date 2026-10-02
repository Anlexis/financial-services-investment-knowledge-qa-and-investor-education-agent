# FIN-C2-111 — Unit Tests: caller trust gate
#
# Every invocation here goes through node(state) — BaseNode.__call__ — which is
# where the trust gate lives (trust check -> input gate -> execute() -> output
# gate). Calling node.execute(state) directly skips __call__ and therefore
# skips the gate entirely, which makes such a test vacuous; no test in this
# file does it.
#
# Denial contract: __call__ RETURNS an error dict (it never raises) carrying
# status ERROR and a "trust gate denied" entry in error_log. execute() does not
# run, so the keys only that node writes are ABSENT from the returned dict.
#
# The assertions below are deliberately node-specific — the exact state keys and
# literal values PreProcessNode itself produces — so that a passing test cannot
# be explained by the framework's generic error backstop, which also returns
# status ERROR when execute() raises.

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.nodes.investor_intent_classify_node import InvestorIntentClassifyNode
from src.nodes.output_format_node import OutputFormatNode
from src.nodes.plain_language_answer_node import PlainLanguageAnswerNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.nodes.product_kb_retrieve_node import ProductKBRetrieveNode
from src.nodes.query_normalize_node import QueryNormalizeNode
from src.nodes.suitability_gate_node import SuitabilityGateNode
from src.nodes.tts_render_node import TTSRenderNode

# Keys that ONLY PreProcessNode.execute() writes. Their absence proves execute()
# never ran, rather than merely proving that something failed somewhere.
# (domain_kb_path / tts_summary_enabled are also execute()-only keys, but they
# are written only when the caller supplies them, so they cannot serve as
# absence probes here.)
_PRE_PROCESS_OUTPUT_KEYS = (
    "validated_input",
    "enriched_context",
)

_QUERY = "NISAの積立投資はどのような仕組みですか"


def _state(trust_value: str, **extra) -> dict:
    """Minimal backbone state with an explicit caller trust level."""
    state = {
        "user_input": _QUERY,
        "input_context": {},
        "caller_trust_level": trust_value,
        "node_history": [],
        "error_log": [],
        "session_id": "test-session",
        "execution_time": {},
    }
    state.update(extra)
    return state


@pytest.fixture(autouse=True)
def silence_audit(monkeypatch):
    """Neutralise the audit sink so these tests assert on the gate, not on audit.

    Patched per node module (never via a sys.modules stub for shared.*, which
    would break the wheel's own shared.* imports at collection time).
    """
    for mod_path in (
        "src.nodes.investor_intent_classify_node",
        "src.nodes.output_format_node",
        "src.nodes.plain_language_answer_node",
        "src.nodes.post_process_node",
        "src.nodes.pre_process_node",
        "src.nodes.product_kb_retrieve_node",
        "src.nodes.query_normalize_node",
        "src.nodes.suitability_gate_node",
        "src.nodes.tts_render_node",
    ):
        monkeypatch.setattr(mod_path + ".emit_trace_event", lambda *a, **k: None)


class TestTrustGateDenial:
    """An under-privileged caller must be stopped before execute() runs."""

    def test_anonymous_caller_denied_on_pre_process(self):
        """ANONYMOUS caller on the VERIFIED_EXTERNAL pre_process gate."""
        node = PreProcessNode()

        result = node(_state(TrustLevel.ANONYMOUS.value))

        assert result.get("status") == AgentStatus.ERROR.value
        denials = [entry for entry in result.get("error_log", []) if "trust gate denied" in str(entry)]
        assert denials, f"expected a trust-gate denial in error_log, got: {result.get('error_log')}"
        # The denial must name THIS node and both trust levels involved, so the
        # assertion cannot be satisfied by an unrelated gate elsewhere.
        denial = str(denials[0])
        assert "PreProcessNode" in denial
        assert TrustLevel.VERIFIED_EXTERNAL.value in denial
        assert TrustLevel.ANONYMOUS.value in denial

    def test_denied_call_produces_no_pre_process_output(self):
        """execute() must not run: none of its output keys may appear."""
        node = PreProcessNode()

        result = node(_state(TrustLevel.ANONYMOUS.value))

        leaked = [key for key in _PRE_PROCESS_OUTPUT_KEYS if key in result]
        assert not leaked, f"trust-gate denial still produced execute() output: {leaked}"

    def test_denial_returns_a_dict_and_never_raises(self):
        """The gate returns an error dict; it must not surface as an exception."""
        node = PreProcessNode()

        result = node(_state(TrustLevel.ANONYMOUS.value))

        assert isinstance(result, dict)
        assert result.get("node_history") == ["PreProcessNode"]


class TestTrustGateAdmission:
    """A sufficiently privileged caller reaches execute() and gets its output."""

    def test_verified_external_caller_passes_pre_process(self):
        node = PreProcessNode()

        result = node(_state(TrustLevel.VERIFIED_EXTERNAL.value))

        assert result.get("status") == AgentStatus.SUCCESS.value
        assert not any("trust gate denied" in str(entry) for entry in result.get("error_log", []))
        # Values only PreProcessNode.execute() writes.
        assert result.get("validated_input") == _QUERY
        assert result.get("enriched_context", {}).get("source") == "InvestmentKnowledgeQAAgent"
        # Omitted caller fields stay unset so the declared config/config.yaml
        # values (seeded into the inner pipeline) apply as defaults.
        assert "domain_kb_path" not in result

    def test_internal_caller_passes_pre_process(self):
        """INTERNAL outranks VERIFIED_EXTERNAL, so the gate admits it too."""
        node = PreProcessNode()

        result = node(_state(TrustLevel.INTERNAL.value))

        assert result.get("status") == AgentStatus.SUCCESS.value
        assert result.get("validated_input") == _QUERY

    def test_gate_runs_before_the_nodes_own_validation(self):
        """Empty input is rejected by the node, not by the trust gate."""
        node = PreProcessNode()

        result = node(_state(TrustLevel.VERIFIED_EXTERNAL.value, user_input="   "))

        assert result.get("status") == AgentStatus.ERROR.value
        assert any("user_input is empty or missing" in str(entry) for entry in result.get("error_log", []))
        assert not any("trust gate denied" in str(entry) for entry in result.get("error_log", []))

    def test_anonymous_caller_admitted_by_inner_domain_node(self):
        """Inner nodes are ANONYMOUS, so the same caller passes there."""
        node = QueryNormalizeNode()

        result = node(_state(TrustLevel.ANONYMOUS.value, validated_input=_QUERY))

        assert result.get("status") == AgentStatus.SUCCESS.value
        assert result.get("normalized_query") == _QUERY
        assert not any("trust gate denied" in str(entry) for entry in result.get("error_log", []))


class TestTrustLevelMatrix:
    """The declared trust matrix: one external gate, everything else internal-facing."""

    def test_pre_process_is_the_external_gate(self):
        assert PreProcessNode.required_trust_level is TrustLevel.VERIFIED_EXTERNAL

    def test_every_other_node_admits_anonymous(self):
        for node_cls in (
            InvestorIntentClassifyNode,
            OutputFormatNode,
            PlainLanguageAnswerNode,
            PostProcessNode,
            ProductKBRetrieveNode,
            QueryNormalizeNode,
            SuitabilityGateNode,
            TTSRenderNode,
        ):
            assert node_cls.required_trust_level is TrustLevel.ANONYMOUS, (
                f"{node_cls.__name__} must declare TrustLevel.ANONYMOUS " "(it runs behind the pre_process gate)"
            )
