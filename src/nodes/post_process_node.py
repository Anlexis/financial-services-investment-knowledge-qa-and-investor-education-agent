"""AgentCore Platform v1.0"""

# PostProcessNode — outer backbone output gate
#
# Final scan after the inner domain workflow completes, applied to the exact
# text that leaves the agent. This template renders NO monetary aggregates of
# its own: the answer text quotes the curated knowledge base — including
# statutory amounts such as annual contribution limits — verbatim, so a
# numeric rounding grid would corrupt legally accurate figures. The output
# invariant this template owns instead is:
#
#   1. Released answers are never empty.
#   2. Every released answer carries the mandated suitability disclaimer
#      (appended by SuitabilityGateNode; its presence is re-verified here at
#      the boundary, fail-closed).
#   3. No credential material leaves the agent.
#
# The framework's own final output gate also runs automatically — this is an
# additional domain check on top of it.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.content_screens import scan_credentials
from src.nodes.suitability_gate_node import SUITABILITY_DISCLAIMER
from src.services.llm_factory import resolve_llm
from src.services.llm_review import render_review, review_result


# Module-level domain scan (not a class method — the framework's own gate
# methods are final and must not be overridden).
def _security_gate_output(result: dict[str, Any]) -> None:
    """Domain output gate: enforce the release invariant on formatted output.

    Raises ValueError when the output is empty, when the mandated
    suitability disclaimer is missing, or when credential material is
    present. Error messages name the violated rule, never the content.
    """
    output_text = str(result.get("formatted_output", ""))
    if not output_text.strip():
        raise ValueError("output gate: released answer must not be empty")
    if SUITABILITY_DISCLAIMER not in output_text:
        raise ValueError("output gate: mandated suitability disclaimer missing from answer")
    if scan_credentials(output_text) is not None:
        raise ValueError("output gate: credential pattern detected in response")


class PostProcessNode(FunctionNode):
    """Verify and release the final output.

    Reads result from the inner workflow (set via merge_output) and produces
    formatted_output for the caller, after enforcing the release invariant
    (non-empty, disclaimer present, credential-free).
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        result = state.get("result", "")

        _llm, _ = resolve_llm(None, state)
        _remarks = review_result(
            _llm,
            user_input=str(state.get("user_input") or ""),
            result=result,
            domain="FIN FinancialLiteracyVoiceAgent",
        )
        _review = render_review(_remarks)
        # Wired in the OUTER node, not the inner graph's output_format_node: extract_input
        # packs only a "query" key into the inner envelope, so user_input never reaches the
        # inner state. A review there would compare the answer against an empty message and
        # report nothing, with no error anywhere -- the silent-drop failure this project has
        # already paid for once.
        #
        # This gate signals by raising, so the merge is attempted and abandoned rather than
        # tested. A tripped review is dropped on its own: an advisory reader that could
        # withhold a correct answer would be changing the outcome.
        if _review and isinstance(result, str):
            try:
                _security_gate_output({"formatted_output": result + _review, "status": AgentStatus.SUCCESS.value})
            except ValueError:
                pass
            else:
                result = result + _review

        delta: dict[str, Any] = {
            "formatted_output": result,
            "status": AgentStatus.SUCCESS.value,
        }

        # Domain output gate (module-level function — never a final-method
        # override). On a violation the node must not merely fail: the
        # response envelope falls back to state["result"] even on an error
        # status, so the blocked text has to be CLEARED from state or it
        # would still ship inside the error envelope. Fail closed by
        # overwriting both output-bearing fields and returning an error.
        try:
            _security_gate_output(delta)
        except ValueError as violation:
            emit_trace_event(
                "post_process_complete",
                {"outcome": "blocked", "reason": "release_invariant_violation"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "result": "",
                "formatted_output": "",
                "error_log": [f"PostProcessNode: {violation}"],
            }

        # Length only — never the response body.
        emit_trace_event(
            "post_process_complete",
            {"outcome": "released", "output_chars": len(str(result))},
            state,
        )

        return delta
