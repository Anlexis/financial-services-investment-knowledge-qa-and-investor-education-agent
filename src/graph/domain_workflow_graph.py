"""AgentCore Platform v1.0"""

# InvestmentWorkflowGraph — FIN-C2-111 inner domain graph
#
# Cat 2 inner graph (BaseGraph) for the investment knowledge Q&A pipeline.
# Called by InvestmentKnowledgeGraphNode.get_subgraph() in graph.py.
#
# Pipeline:
#   START → query_normalize → intent_classify → kb_retrieve →
#           plain_answer → suitability_gate → [conditional] →
#           tts_render (if enabled) → output_format → END
#
# Conditional routing after suitability_gate:
#   tts_summary_enabled=True  → tts_render → output_format
#   tts_summary_enabled=False → output_format (directly)

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from src.nodes.investor_intent_classify_node import InvestorIntentClassifyNode
from src.nodes.output_format_node import OutputFormatNode
from src.nodes.plain_language_answer_node import PlainLanguageAnswerNode
from src.nodes.product_kb_retrieve_node import ProductKBRetrieveNode
from src.nodes.query_normalize_node import QueryNormalizeNode
from src.nodes.suitability_gate_node import SuitabilityGateNode
from src.nodes.tts_render_node import TTSRenderNode
from src.schemas.state import State


class InvestmentWorkflowGraph(BaseGraph):
    """Inner domain graph for investment knowledge Q&A pipeline.

    Inherits BaseGraph for fully custom node topology (no forced backbone).
    Called by InvestmentKnowledgeGraphNode.get_subgraph() in graph.py.

    Domain flow:
        query_normalize → intent_classify → kb_retrieve →
        plain_answer → suitability_gate → [tts_render?] → output_format
    """

    # ── Identity ──────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "investment_knowledge_workflow"

    @property
    def state_schema(self) -> type:
        return State

    # ── Config validation ─────────────────────────────────────────────────

    def _validate_config(self) -> None:
        """No mandatory config for the inner graph.

        InvestmentKnowledgeGraphNode._parent_config() forwards the declared
        runtime parameters (config/config.yaml) under config["configurable"],
        but every domain node keeps a literal fallback, so an empty config is
        not an error.
        """
        pass

    # ── Declared runtime config -> inner state ────────────────────────────

    def _extra_initial_state(self) -> dict[str, Any]:
        """Republish the forwarded runtime config into the inner initial state.

        InvestmentKnowledgeGraphNode._parent_config() puts the declared
        runtime parameters (config/config.yaml) under config["configurable"];
        this hook seeds the two domain-relevant keys (domain_kb_path,
        tts_summary_enabled) into inner state so QueryNormalizeNode can fall
        back to the declared values. Per-request values still win: they
        travel in the JSON envelope built by extract_input() and
        QueryNormalizeNode applies them over these defaults.

        Only keys actually declared in config/config.yaml are seeded, so a
        missing or malformed file leaves the nodes on their own literal
        defaults.
        """
        configurable = (self.config or {}).get("configurable") or {}
        seed: dict[str, Any] = {}
        if "domain_kb_path" in configurable:
            seed["domain_kb_path"] = str(configurable["domain_kb_path"])
        if "tts_summary_enabled" in configurable:
            seed["tts_summary_enabled"] = bool(configurable["tts_summary_enabled"])
        return seed

    # ── Node registration — NO ctor args ──────────────────────────────────

    def register_nodes(self) -> None:
        """Register all domain nodes with no constructor arguments.

        Framework node contract: FunctionNode subclasses have no __init__ and
        keep the execute(self, state) -> dict signature. Declared config
        reaches them through inner state (_extra_initial_state), never
        through ctor args.
        """
        # No super() call — BaseGraph.register_nodes() is abstract.
        self._nodes["query_normalize"] = QueryNormalizeNode()
        self._nodes["intent_classify"] = InvestorIntentClassifyNode()
        self._nodes["kb_retrieve"] = ProductKBRetrieveNode()
        self._nodes["plain_answer"] = PlainLanguageAnswerNode()
        self._nodes["suitability_gate"] = SuitabilityGateNode()
        self._nodes["tts_render"] = TTSRenderNode()
        self._nodes["output_format"] = OutputFormatNode()

    # ── Edge wiring ───────────────────────────────────────────────────────

    def add_edges(self) -> None:
        """Wire the investment Q&A pipeline.

        TTS rendering is optional: after suitability_gate, the graph
        routes to tts_render (if tts_summary_enabled) or output_format directly.
        """
        self._sg.add_edge(START, "query_normalize")
        self._sg.add_edge("query_normalize", "intent_classify")
        self._sg.add_edge("intent_classify", "kb_retrieve")
        self._sg.add_edge("kb_retrieve", "plain_answer")
        self._sg.add_edge("plain_answer", "suitability_gate")
        # Conditional: TTS optional
        self._sg.add_conditional_edges(
            "suitability_gate",
            self.route,
            {
                "tts_render": "tts_render",
                "output_format": "output_format",
            },
        )
        self._sg.add_edge("tts_render", "output_format")
        self._sg.add_edge("output_format", END)

    # ── Routing ───────────────────────────────────────────────────────────

    def route(self, state: State) -> str:
        """Route after suitability_gate based on TTS feature flag.

        The parameter annotation is load-bearing: LangGraph reads the path
        callable's annotation as its input schema and projects the state to
        it. Annotated with the base AgentState, the domain fields (including
        tts_summary_enabled) were filtered out before routing, so the TTS
        branch could never fire. The annotation must be this graph's own
        State schema.
        """
        if state.get("tts_summary_enabled"):
            return "tts_render"
        return "output_format"

    # ── Output shape ──────────────────────────────────────────────────────

    def get_output(self, state: AgentState) -> dict[str, Any]:
        """Shape the sub_result dict returned to InvestmentKnowledgeGraphNode.merge_output().

        Designed together with merge_output() in graph.py — field names must align.
        """
        return {
            "output": state.get("formatted_output") or state.get("answer_text", ""),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
