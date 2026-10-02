"""AgentCore Platform v1.0"""

# ProductKBRetrieveNode — FIN-C2-111 inner domain node
#
# Retrieves relevant investment product documents from the vector KB.
# The kb_path selector is validated against the shared allowlist before any
# access; KB access events are audit-logged via emit_trace_event.

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.content_screens import KB_PATH_RE, scan_credentials

# Deterministic KB stub (simulates vector retrieval for testing and CI)
# In production this would call the configured vector store endpoint.
_KB_DOCUMENTS: dict[str, list[dict[str, Any]]] = {
    "product_info": [
        {
            "doc_id": "KB-NISA-001",
            "title": "NISA積立投資の基本",
            "content": (
                "NISA（少額投資非課税制度）は、年間120万円まで投資信託や株式への"
                "投資利益が非課税になる制度です。2024年のNISA拡充により、"
                "年間投資枠が360万円（成長投資枠240万円＋積立投資枠120万円）に拡大されました。"
            ),
            "score": 0.92,
        },
        {
            "doc_id": "KB-FUND-002",
            "title": "投資信託の仕組みと種類",
            "content": (
                "投資信託は多数の投資家から資金を集め、専門家（ファンドマネージャー）が"
                "株式・債券・不動産等に投資・運用する金融商品です。"
                "主な種類：株式型・債券型・バランス型・インデックス型・アクティブ型。"
            ),
            "score": 0.88,
        },
    ],
    "risk_query": [
        {
            "doc_id": "KB-RISK-001",
            "title": "投資リスクの種類と管理",
            "content": (
                "主な投資リスク：価格変動リスク（株価・基準価額の下落）、"
                "為替リスク（外貨建て資産の為替変動）、信用リスク（発行体のデフォルト）、"
                "流動性リスク（換金困難）。分散投資でリスクを軽減できますが、"
                "元本割れリスクをゼロにすることはできません。"
            ),
            "score": 0.94,
        },
    ],
    "suitability_check": [
        {
            "doc_id": "KB-SUIT-001",
            "title": "投資家の適合性原則",
            "content": (
                "金融商品取引法第40条は適合性の原則を規定しています。"
                "金融機関は顧客の投資目的・リスク許容度・財務状況・投資経験を"
                "十分に把握し、顧客に適した商品を推奨する義務があります。"
                "ご自身の状況に合った商品選択のためにはファイナンシャルアドバイザーへの"
                "相談を推奨します。"
            ),
            "score": 0.91,
        },
    ],
    "general_education": [
        {
            "doc_id": "KB-EDU-001",
            "title": "投資の基礎知識",
            "content": (
                "投資とは、将来の利益を期待して現在の資産を運用することです。"
                "主な投資対象：株式（企業の所有権）、債券（貸付証書）、不動産、"
                "投資信託（運用商品）。長期・分散・積立の3原則が安定した資産形成の基本です。"
            ),
            "score": 0.85,
        },
    ],
}


def _security_gate_output(result: dict[str, Any]) -> None:
    """Module-level gate: verify no credential patterns in retrieval output."""
    docs_text = str(result.get("retrieved_documents", []))
    if scan_credentials(docs_text) is not None:
        raise ValueError("retrieval gate: credential pattern detected in KB retrieval output")


class ProductKBRetrieveNode(FunctionNode):
    """Retrieve relevant documents from investment product knowledge base.

    kb_path is validated against the shared allowlist pattern before use —
    a hard gate against path traversal, kept even though the input boundary
    validates the same field, so the two checks cannot drift apart.
    Retrieval events are audit-logged (counts and identifiers only).
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        query = state.get("normalized_query") or state.get("user_input", "")
        intent = state.get("intent", "general_education")
        kb_path = state.get("domain_kb_path", "investment_products_kb")

        # Validate kb_path against the shared allowlist (safe characters,
        # bounded length — dots and slashes would enable path traversal)
        if not KB_PATH_RE.match(kb_path):
            # Reason code only — never the rejected kb_path value.
            emit_trace_event(
                "kb_retrieve",
                {"outcome": "rejected", "reason": "unsafe_kb_path"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ProductKBRetrieveNode: kb_path is not an allowed knowledge-base name"],
            }

        if not query:
            emit_trace_event(
                "kb_retrieve",
                {"outcome": "rejected", "reason": "empty_query"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ProductKBRetrieveNode: normalized_query is empty"],
            }

        # Retrieve documents by intent (deterministic stub simulating vector search)
        documents = _KB_DOCUMENTS.get(intent, _KB_DOCUMENTS["general_education"])
        top_score = documents[0]["score"] if documents else 0.0

        # dict/list fields are JSON-serialized before storing in State
        # (checkpoint serialization requires flat, msgpack-safe values)
        delta = {
            "retrieved_documents": json.dumps(documents, ensure_ascii=False),
            "retrieval_score": top_score,
            "status": AgentStatus.SUCCESS.value,
        }

        # Domain output gate on the retrieval payload
        _security_gate_output(delta)

        # Audit KB access — counts, identifiers and score only; the caller's
        # query text is never written to the audit stream.
        emit_trace_event(
            "kb_retrieve",
            {
                "intent": intent,
                "kb_path": kb_path,
                "doc_count": len(documents),
                "top_score": top_score,
                "query_chars": len(query),
            },
            state,
        )

        return delta
