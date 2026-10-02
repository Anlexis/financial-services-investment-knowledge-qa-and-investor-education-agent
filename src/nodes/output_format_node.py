"""AgentCore Platform v1.0"""

# OutputFormatNode — FIN-C2-111 inner domain node
#
# Final formatting of the investment Q&A response.
# Combines answer_text (with embedded suitability disclaimer from SuitabilityGateNode)
# and optional tts_audio_url into a structured formatted_output string.
#
# No credential material passes through; the outer PostProcessNode runs the
# same credential scan again on the exact text that leaves the agent.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.content_screens import scan_credentials


def _security_gate_output(result: dict[str, Any]) -> None:
    """Module-level gate: verify no credential patterns in formatted output."""
    output_text = str(result.get("formatted_output", ""))
    if scan_credentials(output_text) is not None:
        raise ValueError("format gate: credential pattern detected in formatted output")


class OutputFormatNode(FunctionNode):
    """Format the final investment Q&A response.

    Combines the answered text (with hardcoded disclaimer already embedded)
    and optional TTS URL into the formatted_output field consumed by
    the outer graph's merge_output() via get_output().
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        answer_text = state.get("answer_text", "")
        tts_url = state.get("tts_audio_url")
        intent = state.get("intent", "general_education")

        if not answer_text:
            # Reason code only.
            emit_trace_event(
                "output_format_complete",
                {"outcome": "rejected", "reason": "empty_answer_text"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputFormatNode: answer_text is empty"],
                # The runner surfaces `formatted_output or result` as `output`. A reason left only in
                # error_log reaches no one: the terminal result carries just `status`, and get_output()
                # does not copy error_log out of the graph -- the caller sees a blank spinner.
                "formatted_output": "Request could not be completed. " + ("OutputFormatNode: answer_text is empty"),
            }

        # Build structured output
        lines = [answer_text]

        if tts_url:
            lines.append(f"\n【音声要約】{tts_url}")

        formatted = "\n".join(lines)

        delta = {
            "formatted_output": formatted,
            "status": AgentStatus.SUCCESS.value,
        }

        # Domain output gate (module-level, not a class method override)
        _security_gate_output(delta)

        # Shape of the response only — never the formatted text.
        emit_trace_event(
            "output_format_complete",
            {
                "outcome": "formatted",
                "intent": intent,
                "output_chars": len(formatted),
                "tts_attached": bool(tts_url),
            },
            state,
        )

        return delta
