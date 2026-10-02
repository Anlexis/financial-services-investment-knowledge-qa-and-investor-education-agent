"""AgentCore Platform v1.0"""

# State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption. Extend AgentState with agent-specific
# fields only. Do NOT add credentials, secrets, or Pydantic models.
#
# JSON serialization rule: dict/list fields must be stored as
# Optional[str] (JSON-serialized). Use the helpers below for safe
# serialize/deserialize; never store raw Python objects in State.

import json
from typing import Any, Optional, cast

from framework.schemas.agent_state import AgentState


# ── JSON serialization helpers ─────────────────────────────────────────────────────


def intent_metadata_to_json(metadata: dict[str, Any]) -> str:
    """Serialize intent_metadata dict to JSON string for State storage."""
    return json.dumps(metadata, ensure_ascii=False)


def intent_metadata_from_json(s: Optional[str]) -> dict[str, Any]:
    """Deserialize intent_metadata from State JSON string."""
    if not s:
        return {}
    return cast("dict[str, Any]", json.loads(s))


def retrieved_documents_to_json(docs: list[Any]) -> str:
    """Serialize retrieved_documents list to JSON string for State storage."""
    return json.dumps(docs, ensure_ascii=False)


def retrieved_documents_from_json(s: Optional[str]) -> list[Any]:
    """Deserialize retrieved_documents from State JSON string."""
    if not s:
        return []
    return cast("list[Any]", json.loads(s))


class State(AgentState):
    """Investment Knowledge Q&A agent state (FIN-C2-111).

    Domain pipeline: QueryNormalize -> InvestorIntentClassify ->
    ProductKBRetrieve -> PlainLanguageAnswer -> SuitabilityGate ->
    TTSRender(optional) -> OutputFormat.

    All fields are Optional because the state is built up progressively
    across nodes; early nodes will not have later fields set.

    dict/list fields are stored as Optional[str] (JSON strings).
    Use intent_metadata_to_json/from_json and
    retrieved_documents_to_json/from_json for serialization.
    """

    # ── Config extracted by outer PreProcessNode from input_context ──────────
    tts_summary_enabled: Optional[bool]
    domain_kb_path: Optional[str]

    # ── Inner domain pipeline fields ─────────────────────────────────────────

    # Set by QueryNormalizeNode
    normalized_query: Optional[str]

    # Set by InvestorIntentClassifyNode
    intent: Optional[str]  # "product_info" | "risk_query" | "suitability_check" | "general_education"
    intent_metadata: Optional[str]  # JSON-serialized dict {"scores": {...}, "confidence": float}

    # Set by ProductKBRetrieveNode
    retrieved_documents: Optional[str]  # JSON-serialized list of document dicts
    retrieval_score: Optional[float]

    # Set by PlainLanguageAnswerNode
    answer_text: Optional[str]

    # Set by SuitabilityGateNode (HARDCODED — never configurable)
    suitability_disclaimer: Optional[str]

    # Set by TTSRenderNode (only when tts_summary_enabled=True)
    tts_audio_url: Optional[str]
