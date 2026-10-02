"""AgentCore Platform v1.0"""

# Node contract:
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Write AgentStatus `.value` strings into State — never the bare enum
#  - Read input_context via _without_platform_context(state.get("input_context", {})) — read-only
#  - Emit a trace event on every execute() path (reason codes / counts only)
#  - Never import from mediator/, api/, or other agents

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.content_screens import (
    CHANNEL_RE,
    KB_PATH_RE,
    scan_context_structure,
    scan_injection,
)


# The Marketplace runner seeds input_context with its own conversation history on every
# invocation (shared/bootstrap/marketplace_app.py); the caller neither sends that key nor can
# suppress it, and the build_input_context hook can only overwrite its value, never remove it.
# It is platform plumbing rather than caller data, so it is dropped here, before the caller
# contract runs: the unknown-field guard below stays strict for everything a caller can
# actually send, and no value screen is ever asked to judge a transcript that contains this
# agent's own earlier answers. The value may also be None, which this tolerates.
_PLATFORM_CONTEXT_KEYS = frozenset({"conversation_history"})


def _without_platform_context(raw: Any) -> Any:
    """The caller-supplied half of input_context, platform-injected keys removed."""
    if not isinstance(raw, dict):
        return raw
    return {k: v for k, v in raw.items() if k not in _PLATFORM_CONTEXT_KEYS}


# Upper bound on the caller's question. Real investor questions are a few
# hundred characters; the cap refuses bulk payloads long before they reach
# retrieval or rendering.
_MAX_INPUT_CHARS = 4000

# The complete caller contract for the structured channel. Anything else in
# input_context is refused — unknown fields are counted, never echoed.
_ALLOWED_CONTEXT_FIELDS = frozenset({"tts_summary_enabled", "domain_kb_path", "channel"})


def _reject(reason: str, message: str, state: dict[str, Any]) -> dict[str, Any]:
    """Uniform refusal: audit the reason code, name the field, echo nothing."""
    emit_trace_event(
        "pre_process_complete",
        {"outcome": "rejected", "reason": reason},
        state,
    )
    return {
        "status": AgentStatus.ERROR.value,
        "error_log": [f"PreProcessNode: {message}"],
        # The runner surfaces `formatted_output or result` as `output`. A reason left only in
        # error_log reaches no one: the terminal result carries just `status`, and get_output()
        # does not copy error_log out of the graph -- the caller sees a blank spinner.
        "formatted_output": "Request could not be completed. " + (f"PreProcessNode: {message}"),
    }


class PreProcessNode(FunctionNode):
    """Validate the caller's question and the structured caller channel.

    This is the external-facing trust gate — VERIFIED_EXTERNAL enforces that
    only authenticated callers reach the domain pipeline. Every caller field
    is validated against explicit bounds and fails CLOSED; rejected values
    are never echoed into errors or logs (the field is named, the value is
    not). There are no caller-controlled numeric fields in this contract —
    the only non-string field, ``tts_summary_enabled``, must be a real
    boolean and coercions such as ``1`` or ``"true"`` are refused.

    Config precedence: values the caller supplies per request win; fields the
    caller omits are left unset here so the declared values from
    ``config/config.yaml`` (seeded into the inner pipeline) apply instead.
    """

    # Backbone external gate: only VERIFIED_EXTERNAL callers may enter.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        user_input = state.get("user_input", "")
        input_context = _without_platform_context(state.get("input_context", {}))  # read-only

        if not isinstance(user_input, str) or not user_input.strip():
            return _reject("empty_input", "user_input is empty or missing", state)

        stripped = user_input.strip()
        if len(stripped) > _MAX_INPUT_CHARS:
            return _reject(
                "input_too_long",
                f"user_input exceeds the {_MAX_INPUT_CHARS}-character limit",
                state,
            )

        # Instruction-override screen over the question text — the template's
        # own guarantee, independent of any platform-side scan. The screen
        # name is audited; neither it nor the text is echoed to the caller.
        if scan_injection(stripped) is not None:
            return _reject(
                "injection_pattern",
                "user_input rejected by the instruction-override screen",
                state,
            )

        if not isinstance(input_context, dict):
            return _reject("context_not_mapping", "input_context must be an object", state)

        unknown = [key for key in input_context if key not in _ALLOWED_CONTEXT_FIELDS]
        if unknown:
            # Field names are caller-controlled text — report the count only.
            return _reject(
                "unknown_context_field",
                f"input_context carries {len(unknown)} unrecognized field(s)",
                state,
            )

        # Screen the whole structure — keys included — before any field is
        # read. JSON escape forms are already decoded at this point, so an
        # escaped directive cannot slip past the scan.
        if scan_context_structure(input_context) is not None:
            return _reject(
                "context_injection_pattern",
                "input_context rejected by the instruction-override screen",
                state,
            )

        delta: dict[str, Any] = {}

        if "tts_summary_enabled" in input_context:
            tts_enabled = input_context["tts_summary_enabled"]
            if not isinstance(tts_enabled, bool):
                return _reject(
                    "tts_flag_not_boolean",
                    "input_context.tts_summary_enabled must be a boolean",
                    state,
                )
            delta["tts_summary_enabled"] = tts_enabled

        if "domain_kb_path" in input_context:
            kb_path = input_context["domain_kb_path"]
            if not isinstance(kb_path, str) or not KB_PATH_RE.match(kb_path):
                return _reject(
                    "unsafe_kb_path",
                    "input_context.domain_kb_path is not an allowed knowledge-base name",
                    state,
                )
            delta["domain_kb_path"] = kb_path

        channel = "unknown"
        if "channel" in input_context:
            channel = input_context["channel"]
            if not isinstance(channel, str) or not CHANNEL_RE.match(channel):
                return _reject(
                    "invalid_channel",
                    "input_context.channel is not an allowed channel identifier",
                    state,
                )

        # Counts and flags only — never the caller's question text.
        emit_trace_event(
            "pre_process_complete",
            {
                "outcome": "accepted",
                "input_chars": len(stripped),
                "tts_summary_enabled": delta.get("tts_summary_enabled", False),
            },
            state,
        )

        delta.update(
            {
                "validated_input": stripped,
                "enriched_context": {
                    "source": "InvestmentKnowledgeQAAgent",
                    "channel": channel,
                },
                "status": AgentStatus.SUCCESS.value,
            }
        )
        return delta
