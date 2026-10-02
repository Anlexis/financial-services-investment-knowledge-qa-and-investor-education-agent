# PB-6: Backbone Invoke Order — FIN-C2-111
#
# Runs a full Graph().invoke() over a SUCCESS-yielding payload with an
# EXTERNAL InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
# and asserts backbone node_history order.
#
# Why VERIFIED_EXTERNAL (never for_internal()):
#   InvestmentKnowledgeGraphNode.get_subgraph() passes the outer InvocationContext
#   into the inner InvestmentWorkflowGraph unchanged. If any inner domain node
#   declared TrustLevel.INTERNAL, a VERIFIED_EXTERNAL(1) caller would be denied
#   at the inner gate (1 < 2) → SubgraphError → PostProcessNode SKIPPED. This
#   test catches that trust-trap: a caller=INTERNAL context masks the trap
#   because INTERNAL(2) ≥ everything.
#
# The point: a real external caller (VERIFIED_EXTERNAL) must reach PostProcessNode.

import pytest
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

# ── Template-specific constants ────────────────────────────────────────────────

# The class name of the GraphNode subclass assigned to the `main` slot in
# src/graph/graph.py.  Must match exactly what is stored in node_history.
_MAIN_SLOT_NODE = "InvestmentKnowledgeGraphNode"

# A SUCCESS-yielding investment question for a retail investor.
# Passes PreProcessNode (non-empty, no injection directives) and the entire
# inner InvestmentWorkflowGraph pipeline producing a valid answer.
_VALID_PAYLOAD = "NISAとは何ですか？積立投資信託について教えてください"

# Expected backbone node_history order for a SUCCESS path.
# Non-SUCCESS status (e.g., ERROR from pre_process) short-circuits main → finalize,
# skipping post_process — so SUCCESS is load-bearing for this assertion.
_EXPECTED_BACKBONE = [
    "InitializeNode",
    "PreProcessNode",
    _MAIN_SLOT_NODE,
    "PostProcessNode",
    "FinalizeNode",
]

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_domain_emit(monkeypatch):
    """Silence emit_trace_event in domain node modules.

    The CI wheel provides the real shared.* package, but these calls attempt
    to write to an audit backend that is not available in test environments.
    Patch at the node module level (NOT via sys.modules stub — that breaks
    the wheel's own shared.security import at collection time).
    """
    for mod_path in (
        "src.nodes.product_kb_retrieve_node",
        "src.nodes.plain_language_answer_node",
        "src.nodes.suitability_gate_node",
    ):
        monkeypatch.setattr(mod_path + ".emit_trace_event", lambda *a, **k: None)


# ── PB-6 Test ─────────────────────────────────────────────────────────────────


class TestPB6BackboneInvokeOrder:
    """PB-6: VERIFIED_EXTERNAL caller must traverse the full backbone to PostProcessNode.

    A non-SUCCESS status short-circuits main → finalize and skips post_process,
    so the SUCCESS assertion on _VALID_PAYLOAD is load-bearing.
    """

    def test_verified_external_caller_traverses_full_backbone(self):
        """Full Graph().invoke() with VERIFIED_EXTERNAL asserts backbone order.

        Proves no trust-trap: if an inner domain node had declared INTERNAL trust,
        a VERIFIED_EXTERNAL(1) caller would be denied at the inner gate (1 < 2),
        raising SubgraphError and skipping PostProcessNode — caught here as
        a node_history mismatch.
        """
        from src.graph.graph import InvestmentKnowledgeQAAgent

        agent = InvestmentKnowledgeQAAgent()
        agent.compile()

        # EXTERNAL caller — the only trust path that exercises the trust-trap check.
        # NEVER use InvocationContext.for_internal() here.
        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)

        result = agent.invoke(
            _VALID_PAYLOAD,
            input_context={"tts_summary_enabled": False},
            ctx=ctx,
        )

        # Assert SUCCESS — if pre_process or the inner pipeline returned ERROR,
        # post_process would be skipped and the node_history check below would also fail.
        assert result.get("status") == AgentStatus.SUCCESS, (
            f"Expected SUCCESS from a valid investment query but got "
            f"'{result.get('status')}'. "
            f"error_log: {result.get('error_log', [])}"
        )

        history = result.get("node_history", [])

        assert history == _EXPECTED_BACKBONE, (
            f"Backbone node_history order mismatch — trust-trap suspected if "
            f"PostProcessNode is missing.\n"
            f"Expected: {_EXPECTED_BACKBONE}\n"
            f"Actual:   {history}"
        )

    def test_post_process_reachable_by_verified_external(self):
        """PostProcessNode must appear in node_history for VERIFIED_EXTERNAL callers.

        This is the critical trust-trap check: if any inner node had INTERNAL trust,
        the inner gate would deny the VERIFIED_EXTERNAL(1) caller (1 < 2) and
        SubgraphError would cause the backbone to skip post_process entirely.
        """
        from src.graph.graph import InvestmentKnowledgeQAAgent

        agent = InvestmentKnowledgeQAAgent()
        agent.compile()

        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
        result = agent.invoke(_VALID_PAYLOAD, ctx=ctx)

        history = result.get("node_history", [])
        assert "PostProcessNode" in history, (
            f"PostProcessNode not reached by VERIFIED_EXTERNAL caller — "
            f"trust-trap detected (inner node with INTERNAL trust?). "
            f"node_history: {history}"
        )
        assert _MAIN_SLOT_NODE in history, (
            f"{_MAIN_SLOT_NODE} not in node_history — main slot did not execute. " f"node_history: {history}"
        )
