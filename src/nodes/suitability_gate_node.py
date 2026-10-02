"""AgentCore Platform v1.0"""

# SuitabilityGateNode — FIN-C2-111 inner domain node
#
# HARDCODED 金融商品取引法 suitability disclaimer gate.
#
# This node appends the legally mandated disclaimer to every answer.
# The disclaimer text is a compile-time constant, NOT configurable via
# the manifest, config/config.yaml, input_context, or any runtime
# parameter. Overriding or skipping it would be a regulatory violation.
#
# Disclaimer application is audit-logged for compliance traceability.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# ── HARDCODED DISCLAIMER — DO NOT MAKE CONFIGURABLE ───────────────────────────
# Source: 金融商品取引法 (Financial Instruments and Exchange Act)
# Obligation: every investment-related answer must carry this text.
# This constant must not be replaced with a config-driven value; the output
# boundary (PostProcessNode) independently verifies its presence before any
# answer is released.
SUITABILITY_DISCLAIMER: str = (
    "\n\n"
    "【重要：金融商品取引法に基づく説明義務】\n"
    "本情報は投資判断の参考として提供するものであり、特定の金融商品の購入・売却を"
    "推奨するものではありません。投資に際しては必ずご自身の判断と責任において決定し、"
    "目論見書・契約締結前交付書面等の法定開示書類を事前にご確認ください。"
    "投資には元本割れリスクを伴う場合があります。"
    "お客様の投資目的・リスク許容度・財務状況等を十分にご考慮ください。"
    "\n"
    "（本エージェントは金融商品取引業者ではなく、投資助言・代理業の登録を行っていません。）"
)
# ── END HARDCODED DISCLAIMER ──────────────────────────────────────────────────


class SuitabilityGateNode(FunctionNode):
    """Apply the hardcoded 金融商品取引法 suitability disclaimer.

    This node ALWAYS appends SUITABILITY_DISCLAIMER to answer_text.
    There is no config flag to disable it — this is by design, and the
    output boundary re-verifies the disclaimer's presence independently.
    Every disclaimer application is audit-logged.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        answer = state.get("answer_text", "")

        # Always append — no config-based short-circuit allowed
        answer_with_disclaimer = answer + SUITABILITY_DISCLAIMER

        # Compliance audit log (log the fact of application, not the text)
        emit_trace_event(
            "suitability_disclaimer_applied",
            {"disclaimer_applied": True, "answer_length_before": len(answer)},
            state,
        )

        return {
            "answer_text": answer_with_disclaimer,
            "suitability_disclaimer": SUITABILITY_DISCLAIMER,
            "status": AgentStatus.SUCCESS.value,
        }
