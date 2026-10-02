"""AgentCore Platform v1.0"""

# InvestorIntentClassifyNode — FIN-C2-111 inner domain node
#
# Classifies the investor's query intent to guide downstream retrieval.
# Intent categories map to KB retrieval strategies and answer templates.

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Intent taxonomy for NISA 2.0 retail investors
_INTENT_KEYWORDS = {
    "risk_query": [
        "リスク",
        "risk",
        "損失",
        "元本割れ",
        "価格変動",
        "為替リスク",
        "危険",
        "損する",
        "下がる",
        "暴落",
    ],
    "suitability_check": [
        "向いている",
        "適している",
        "suitability",
        "私に合う",
        "初心者",
        "おすすめ",
        "どれがいい",
        "選び方",
        "比較",
    ],
    "product_info": [
        "投資信託",
        "株式",
        "債券",
        "ETF",
        "NISA",
        "iDeCo",
        "積立",
        "とは",
        "仕組み",
        "種類",
        "説明",
        "教えて",
    ],
    "general_education": [
        "勉強",
        "学ぶ",
        "入門",
        "基礎",
        "わかりやすく",
        "初めて",
        "investment",
        "fund",
        "what is",
        "explain",
    ],
}

_DEFAULT_INTENT = "general_education"


def _classify_intent(query: str) -> tuple[str, dict[str, Any]]:
    """Rule-based intent classification with confidence scores."""
    lower = query.lower()
    scores: dict[str, int] = {intent: 0 for intent in _INTENT_KEYWORDS}

    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in lower:
                scores[intent] += 1

    best_intent = max(scores, key=lambda k: scores[k])
    if scores[best_intent] == 0:
        best_intent = _DEFAULT_INTENT

    total = sum(scores.values()) or 1
    confidence = round(scores[best_intent] / total, 2)

    return best_intent, {"scores": scores, "confidence": confidence}


class InvestorIntentClassifyNode(FunctionNode):
    """Classify investor query intent.

    Outputs:
      intent: "product_info" | "risk_query" | "suitability_check" | "general_education"
      intent_metadata: {"scores": {...}, "confidence": float}
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        query = state.get("normalized_query") or state.get("user_input", "")

        if not query:
            # Reason code only.
            emit_trace_event(
                "investor_intent_classify_complete",
                {"outcome": "rejected", "reason": "no_query"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InvestorIntentClassifyNode: no query available for classification"],
                # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                # error_log reaches no one: the terminal result carries just `status`, and get_output()
                # does not copy error_log out of the graph -- the caller sees a blank spinner.
                "formatted_output": "Request could not be completed. "
                + ("InvestorIntentClassifyNode: no query available for classification"),
            }

        intent, metadata = _classify_intent(query)

        # Intent label + confidence only — never the query text.
        emit_trace_event(
            "investor_intent_classify_complete",
            {
                "outcome": "classified",
                "intent": intent,
                "confidence": metadata.get("confidence"),
            },
            state,
        )

        # dict fields are JSON-serialized before storing in State
        # (checkpoint serialization requires flat, msgpack-safe values)
        return {
            "intent": intent,
            "intent_metadata": json.dumps(metadata, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }
