"""AgentCore Platform v1.0"""

# TTSRenderNode — FIN-C2-111 inner domain node
#
# Optional TTS (Text-to-Speech) audio summary generation.
# Only executes when tts_summary_enabled=True in state (set by QueryNormalizeNode
# from caller-supplied input_context). The inner graph's conditional routing
# skips this node entirely when the flag is False.
#
# In production, this would call a TTS service (e.g. Google TTS, Azure TTS).
# The CI/stub implementation returns a deterministic placeholder URL.

import hashlib
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class TTSRenderNode(FunctionNode):
    """Generate an audio summary of the investment answer (optional).

    Only runs when routed via the inner graph's conditional edge
    (tts_summary_enabled=True). Returns tts_audio_url in state.

    Production: calls configured TTS provider.
    CI/stub: returns deterministic placeholder URL for testing.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        answer = state.get("answer_text", "")

        if not answer:
            # Reason code only.
            emit_trace_event(
                "tts_render_complete",
                {"outcome": "rejected", "reason": "empty_answer"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["TTSRenderNode: answer_text is empty, cannot render TTS"],
                # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                # error_log reaches no one: the terminal result carries just `status`, and get_output()
                # does not copy error_log out of the graph -- the caller sees a blank spinner.
                "formatted_output": "Request could not be completed. "
                + ("TTSRenderNode: answer_text is empty, cannot render TTS"),
            }

        # Deterministic stub URL (hash of answer content for test repeatability)
        # In production: replace with real TTS API call
        content_hash = hashlib.sha256(answer.encode()).hexdigest()[:16]
        tts_url = f"https://tts.placeholder/audio/{content_hash}.mp3"

        # Counts only — never the answer text or the rendered URL.
        emit_trace_event(
            "tts_render_complete",
            {"outcome": "rendered", "answer_chars": len(answer)},
            state,
        )

        return {
            "tts_audio_url": tts_url,
            "status": AgentStatus.SUCCESS.value,
        }
