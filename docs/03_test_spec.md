# Test Specification — FIN-C2-111 InvestmentKnowledgeQAAgent

## Overview

Unit, boundary, and end-to-end tests for the nested investment knowledge Q&A
agent. The two security boundaries are tested in both directions: every
attack/violation form is refused, and realistic investor content containing
the same surface forms passes.

## Test Categories

### Domain Node Tests (`tests/unit/test_agent.py`)

| Test Class | Node | Coverage |
|-----------|------|----------|
| TestQueryNormalizeNode | QueryNormalizeNode | Plain/JSON envelope input, seeded-config fallback, non-mapping JSON, whitespace collapse, empty input, trust level, no-ctor-args |
| TestInvestorIntentClassifyNode | InvestorIntentClassifyNode | All four intent categories, default fallback, empty query, trust level |
| TestProductKBRetrieveNode | ProductKBRetrieveNode | Happy path, unsafe/overlong kb_path refused without echo, empty query, audit payload carries no query text, trust level |
| TestPlainLanguageAnswerNode | PlainLanguageAnswerNode | Answer synthesis, empty-KB fallback, audit payload carries no answer text, empty query, trust level |
| TestSuitabilityGateNode | SuitabilityGateNode | Disclaimer always appended, not disableable, compile-time constant (not a class attribute), audit event, trust level |
| TestTTSRenderNode | TTSRenderNode | Deterministic URL, empty answer, trust level |
| TestOutputFormatNode | OutputFormatNode | With/without TTS URL, credential refusal, empty answer, trust level |
| TestPreProcessNode | PreProcessNode | Config extraction, omitted-fields-stay-unset, empty input, injection refusal, trust level |
| TestPostProcessNode | PostProcessNode | Disclaimed release, credential block clears output fields, trust level |

### Content Screens (`tests/unit/test_content_screens.py`)

| Class | Coverage |
|---|---|
| TestInjectionScreen | Attack matrix (chat-template control tokens, override/exfiltration phrases EN+JA, whitespace-spread forms) refused; realistic investor sentences with the same words pass |
| TestContextStructureScan | Depth-first scan of the structured channel: hostile values, hostile KEYS, nested payloads, escaped payloads post-parse, clean controls, depth cap |
| TestCredentialScreens | Each credential class caught; statutory amounts, decimals, and ordinary prose pass |
| TestIdentifierBounds | kb_path and channel allowlists, both directions, length bounds |

### Caller Contract (`tests/unit/test_input_validation.py`)

Proven by calling `execute()` directly — no framework wrapper in front — so
the guarantees hold wherever the template runs.

| Class | Coverage |
|---|---|
| TestUserInputBounds | Non-string/empty/overlong input refused; at-limit accepted; injection matrix refused without echo; legitimate directive-word questions accepted |
| TestContextFieldBounds | Unknown fields (including smuggled numerics such as NaN) refused without echo; strict-boolean TTS flag; kb_path/channel bounds; hostile field names and values; omitted fields stay unset |

### Output Gate (`tests/unit/test_output_gate.py`)

| Class | Coverage |
|---|---|
| TestReleasePath | Disclaimed answers released byte-identically (statutory amounts, percentages, decimals untouched) |
| TestBlockedPath | Empty output, missing/partial disclaimer, and each credential class block the release; blocked contract clears both output-bearing fields; nothing echoed; audit event emitted |

### Trust Gate (`tests/unit/test_trust_gate.py`)

Denial and admission through `node.__call__` (the gate lives there, not in
`execute()`): under-privileged callers stopped before `execute()` runs with
no output keys leaked; privileged callers pass; the declared trust matrix
(one external gate, inner nodes internal-facing) is pinned.

### Framework Compliance (`tests/unit/test_framework_compliance_tc06_tc07.py`)

TC-06/TC-07: the framework's final input/output gate methods cannot be
overridden by node subclasses.

### Proof-of-Boundary Tests (`tests/proof_of_boundary/`)

| Test | File | Purpose |
|------|------|---------|
| PB-6: Backbone invoke order | `test_pb_invoke_order.py` | Full invoke() as VERIFIED_EXTERNAL traverses initialize → pre_process → main → post_process → finalize (trust-trap detection) |
| Entry-point auth boundary | `test_server_boot.py` | Bearer boundary on POST /invoke through the real ASGI app: 401 matrix, generic body, trust promotion/preservation, input_context forwarding |
| PB-4: Import isolation | `test_import_isolation.py` | No platform-internal SDK imports |
| PB-2/PB-5: State safety | `test_state_safety.py` | State is a flat TypedDict; no credential-like fields |
| PB-7: HITL propagation | `test_pb7_hitl_interrupt_propagation.py` | Skip stub — this template does not enable cross-boundary HITL propagation |

### End-to-End (`tests/integration/test_e2e_invoke.py`)

Through the real ASGI `/invoke` with Bearer auth:

| Class | Coverage |
|---|---|
| TestInvokeHappyPath | Real non-empty disclaimed answer from a valid question; TTS path reachable via input_context |
| TestInvokeRejectionPaths | Validation rejection and injection rejection release nothing and echo nothing; raw `NaN`/`-Infinity` JSON literals over the wire are refused |
| TestDeclaredConfigArrival | Declared config/config.yaml values reach the graph constructor AND the inner pipeline end-to-end (distinct-value proof); per-request values win over declared defaults |
| TestErrorEnvelopeContainment | A blocked release surfaces a clean error envelope — no released text, no traceback, no source paths |

## Critical Compliance Test

`TestSuitabilityGateNode.test_disclaimer_is_compile_time_constant` verifies:

1. `SUITABILITY_DISCLAIMER` is a module-level constant
2. It contains "金融商品取引法" and "元本割れリスク"
3. It is NOT a class attribute (prevents override via subclassing)

`tests/unit/test_output_gate.py::TestBlockedPath::test_missing_disclaimer_blocked`
adds the boundary-side guarantee: an answer without the disclaimer is never
released.

## Test Execution

```bash
pytest tests/ -v
pytest tests/unit/test_agent.py::TestSuitabilityGateNode -v  # compliance tests
pytest tests/proof_of_boundary/ -v
pytest tests/integration/ -v
```

## CI Notes

- `emit_trace_event` is patched per-test via `monkeypatch.setattr` at the node module level
- No `sys.modules` stubs for `shared.*` — the installed wheel provides the real package
- `framework.*` is provided by the `agenticstar-agentcore` wheel pinned in CI
