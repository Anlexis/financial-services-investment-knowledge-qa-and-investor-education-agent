"""AgentCore Platform v1.0"""

# QueryNormalizeNode — FIN-C2-111 inner domain node
#
# Deserializes the JSON-encoded extract_input() string produced by
# InvestmentKnowledgeGraphNode and normalizes the query text. Per-request
# config (tts_summary_enabled, domain_kb_path) travels in the same envelope
# and is applied over the declared defaults seeded into inner state.

import json
import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Literal last-resort defaults, used only when neither the request envelope
# nor the config-seeded inner state supplies a value.
_DEFAULT_KB_PATH = "investment_products_kb"
_DEFAULT_TTS_ENABLED = False


class QueryNormalizeNode(FunctionNode):
    """Normalize the incoming investment query.

    Reads the JSON-serialized user_input from extract_input() and:
    - Extracts the plain query string
    - Propagates per-request config into inner state
    - Normalizes whitespace and encoding

    Config precedence for domain_kb_path / tts_summary_enabled:
    request envelope > config/config.yaml values seeded into inner state by
    InvestmentWorkflowGraph._extra_initial_state() > the literal defaults
    above.
    """

    # Inner domain node: ANONYMOUS (outer backbone already gated VERIFIED_EXTERNAL)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("validated_input") or state.get("user_input", "")

        # Config-seeded defaults (see the graph's _extra_initial_state());
        # the literals below apply only when nothing was declared.
        seeded_kb_path = str(state.get("domain_kb_path") or _DEFAULT_KB_PATH)
        seeded_tts = bool(state.get("tts_summary_enabled", _DEFAULT_TTS_ENABLED))

        # Deserialize the JSON envelope produced by extract_input(). A
        # non-mapping parse (a bare JSON number, for instance) is treated the
        # same as unparseable input: the raw text is the query and the seeded
        # config stays in force.
        try:
            params = json.loads(raw) if isinstance(raw, str) else {}
            if not isinstance(params, dict):
                params = {"query": raw}
            query = str(params.get("query", raw))
            tts_enabled = bool(params.get("tts_summary_enabled", seeded_tts))
            kb_path = str(params.get("domain_kb_path") or seeded_kb_path)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Fallback: treat raw as a plain query string, keep the seeded config
            query = str(raw)
            tts_enabled = seeded_tts
            kb_path = seeded_kb_path

        if not query.strip():
            # Reason code only — the raw envelope is never logged.
            emit_trace_event(
                "query_normalize_complete",
                {"outcome": "rejected", "reason": "empty_query"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["QueryNormalizeNode: query is empty after normalization"],
                # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                # error_log reaches no one: the terminal result carries just `status`, and get_output()
                # does not copy error_log out of the graph -- the caller sees a blank spinner.
                "formatted_output": "Request could not be completed. "
                + ("QueryNormalizeNode: query is empty after normalization"),
            }

        # Normalize: collapse whitespace, strip leading/trailing
        normalized = re.sub(r"\s+", " ", query).strip()

        # Length and flags only — never the normalized query text.
        emit_trace_event(
            "query_normalize_complete",
            {
                "outcome": "normalized",
                "query_chars": len(normalized),
                "tts_summary_enabled": tts_enabled,
            },
            state,
        )

        return {
            "normalized_query": normalized,
            "tts_summary_enabled": tts_enabled,
            "domain_kb_path": kb_path,
            "status": AgentStatus.SUCCESS.value,
        }
