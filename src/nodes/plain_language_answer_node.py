"""AgentCore Platform v1.0"""

# PlainLanguageAnswerNode — FIN-C2-111 inner domain node
#
# Generates a plain-language investment Q&A answer from retrieved documents.
# Synthesizes KB content into readable text for NISA 2.0 first-time investors.
# Answer generation is audit-logged.

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


def _synthesize_answer(query: str, documents: list[dict[str, Any]], intent: str) -> str:
    """Synthesize a plain-language answer from retrieved documents.

    In production this would call the LLM with the retrieved context.
    This deterministic implementation concatenates the top document
    content with intent-specific framing, suitable for CI and PB tests.
    """
    if not documents:
        return (
            "申し訳ありませんが、ご質問に関連する情報が見つかりませんでした。"
            "詳しくは金融機関またはファイナンシャルアドバイザーにお問い合わせください。"
        )

    # Use top document content
    top_doc = documents[0]
    content = top_doc.get("content", "")
    title = top_doc.get("title", "")

    intent_framing = {
        "product_info": "以下に、ご質問の投資商品についてわかりやすくご説明します：",
        "risk_query": "投資のリスクについて、以下の通りご説明します：",
        "suitability_check": "投資適合性について、以下の情報をご参考ください：",
        "general_education": "投資の基礎知識として、以下をご参考ください：",
    }

    framing = intent_framing.get(intent, intent_framing["general_education"])
    return f"{framing}\n\n【{title}】\n{content}"


class PlainLanguageAnswerNode(FunctionNode):
    """Generate a plain-language answer from retrieved investment documents.

    Produces answer_text for NISA 2.0 retail investors (no prior knowledge assumed).
    SuitabilityGateNode appends the mandatory 金商法 disclaimer downstream.
    Generation events are audit-logged.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        query = state.get("normalized_query") or state.get("user_input", "")
        # retrieved_documents is JSON-serialized in State; deserialize on read
        raw_docs = state.get("retrieved_documents")
        documents = json.loads(raw_docs) if isinstance(raw_docs, str) and raw_docs else []
        intent = state.get("intent", "general_education")

        if not query:
            # Reason code only.
            emit_trace_event(
                "answer_generated",
                {"outcome": "rejected", "reason": "no_query"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PlainLanguageAnswerNode: no query to answer"],
                # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                # error_log reaches no one: the terminal result carries just `status`, and get_output()
                # does not copy error_log out of the graph -- the caller sees a blank spinner.
                "formatted_output": "Request could not be completed. "
                + ("PlainLanguageAnswerNode: no query to answer"),
            }

        answer = _synthesize_answer(query, documents, intent)

        # Log the generation event (never the full answer text)
        emit_trace_event(
            "answer_generated",
            {
                "intent": intent,
                "doc_count": len(documents),
                "answer_length": len(answer),
            },
            state,
        )

        return {
            "answer_text": answer,
            "status": AgentStatus.SUCCESS.value,
        }
