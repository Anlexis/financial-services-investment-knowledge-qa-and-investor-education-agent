"""AgentCore Platform v1.0"""

# FIN-C2-111 — InvestmentKnowledgeQAAgent
# Cat 2 outer graph: AgentBaseGraph + GraphNode in the main slot.
#
# Architecture (Cat 2 NESTED):
#   Outer backbone: initialize → pre_process → main → post_process → finalize
#   main slot:      InvestmentKnowledgeGraphNode (GraphNode subclass)
#   Inner graph:    InvestmentWorkflowGraph (BaseGraph) at domain_workflow_graph.py
#
# Class name match rule:
#   config/agent.yaml  class: "src.graph.graph.InvestmentKnowledgeQAAgent"
#   src/api/server.py  from src.graph.graph import InvestmentKnowledgeQAAgent

import json
from pathlib import Path
from typing import Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel

from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State

# Runtime-parameter file location: src/graph/graph.py -> parents[2] is the
# repo root. config/config.yaml holds the runtime parameters (max_retry,
# domain_kb_path, tts_summary_enabled); config/agent.yaml is the static
# manifest and carries no runtime values.
_RUNTIME_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _runtime_config() -> dict[str, Any]:
    """Read the runtime parameters out of config/config.yaml.

    Returns an empty dict — never raises — when the file is absent,
    unreadable, not valid YAML, or not a mapping. Callers treat an empty
    result as "no declared runtime config to forward".
    """
    try:
        import yaml

        loaded = yaml.safe_load(_RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


class InvestmentKnowledgeGraphNode(GraphNode):
    """Wraps the inner InvestmentWorkflowGraph; assigned to the `main` slot.

    Implements the GraphNode contract:
      get_subgraph()   — instantiate the inner domain graph
      extract_input()  — JSON-encode query + per-request config for the inner graph
      merge_output()   — map inner sub_result back to outer state
    """

    # Inner errors propagate as SubgraphError (fail-fast, traceable).
    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    # Inner domain nodes declare ANONYMOUS; outer GraphNode inherits from
    # GraphNode which handles its own trust semantics through the backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def _parent_config(self) -> dict[str, Any]:
        """Forward the declared runtime parameters to the inner graph.

        The domain-relevant keys of config/config.yaml (domain_kb_path,
        tts_summary_enabled) are handed to InvestmentWorkflowGraph under
        config["configurable"]. The inner graph republishes them into inner
        state via _extra_initial_state(), which is what makes the declared
        values reachable by the domain nodes instead of dead config text.

        Degrades to {} — never raises — when the file is missing or
        malformed; the domain nodes keep their own literal defaults in that
        case.
        """
        config = _runtime_config()
        if not config:
            return {}
        return {"configurable": config}

    def get_subgraph(self) -> Any:
        """Instantiate and return the inner domain workflow graph.

        The declared runtime config travels through the BaseGraph
        constructor; the domain NODES still take no constructor arguments and
        keep the execute(self, state) -> dict signature.
        """
        from src.graph.domain_workflow_graph import InvestmentWorkflowGraph

        return InvestmentWorkflowGraph(config=self._parent_config())

    def extract_input(self, state: AgentState) -> str:
        """JSON-encode the query and per-request config for the inner graph.

        Only fields the caller actually supplied travel in the envelope —
        PreProcessNode leaves omitted fields unset, so the declared values
        seeded from config/config.yaml by _extra_initial_state() stay in
        force as defaults. Per-request values, when present, win.
        """
        query = state.get("validated_input", state.get("user_input", ""))
        envelope: dict[str, Any] = {"query": query}
        tts_enabled = state.get("tts_summary_enabled")
        if tts_enabled is not None:
            envelope["tts_summary_enabled"] = bool(tts_enabled)
        kb_path = state.get("domain_kb_path")
        if kb_path is not None:
            envelope["domain_kb_path"] = str(kb_path)
        return json.dumps(envelope, ensure_ascii=False)

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        """Map inner sub_result fields back into the outer state.

        Designed together with InvestmentWorkflowGraph.get_output() — field
        names align. Returns ONLY changed keys (never full state).
        """
        return {
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }


class InvestmentKnowledgeQAAgent(AgentBaseGraph):
    """FIN-C2-111 Investment Knowledge Q&A Agent (Cat 2 outer graph).

    Fixed 5-node backbone; domain complexity encapsulated in
    InvestmentKnowledgeGraphNode.
    Backbone: initialize → pre_process → main → post_process → finalize
    """

    @property
    def name(self) -> str:
        return "InvestmentKnowledgeQAAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # fills: initialize, finalize (required)
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = InvestmentKnowledgeGraphNode()
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
