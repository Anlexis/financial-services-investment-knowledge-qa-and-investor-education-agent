# Design Specification — FIN-C2-111 InvestmentKnowledgeQAAgent

## Position in AgentCore Architecture

| Field | Value |
|---|---|
| Template ID | FIN-C2-111 |
| Agent Class | `InvestmentKnowledgeQAAgent` |
| Category | Cat 2 — domain-specific pipeline (FIN industry) |
| Pattern | Retrieval Q&A over a curated domain knowledge base |
| L1 Base (framework base class) | `AgentBaseGraph` (outer) + `BaseGraph` (inner) — direct framework inheritance |

Three-layer separation:

- State: flat `TypedDict` (`State(AgentState)`) — no Pydantic (msgpack-safe)
- Node: `FunctionNode` inheritance — `execute(self, state: dict) -> dict`
- Graph: `AgentBaseGraph` (outer, 5-node backbone) + `BaseGraph` (inner, custom topology)

## Architecture Overview

### Nested Structure

```
Outer backbone (AgentBaseGraph):
  START → InitializeNode → PreProcessNode(VERIFIED_EXTERNAL) →
          InvestmentKnowledgeGraphNode(GraphNode) →
          PostProcessNode(ANONYMOUS, output gate) → FinalizeNode → END

Inside InvestmentKnowledgeGraphNode.get_subgraph():
  InvestmentWorkflowGraph (BaseGraph):
    START → query_normalize → intent_classify → kb_retrieve →
            plain_answer → suitability_gate → [conditional] → output_format → END
                                                  ↓ (tts_summary_enabled=True)
                                               tts_render → output_format → END
```

Routing note: the conditional edge's path callable is annotated with this
graph's own `State` schema. The annotation is load-bearing — the graph
runtime projects the state to the callable's annotated schema, and an
annotation of the base `AgentState` would filter out the domain fields the
route depends on.

### Node Configuration

| Slot | Class | Responsibility | Trust Level |
|------|-------|---------------|-------------|
| initialize | `InitializeNode` (default) | Session init, schema_version | — |
| pre_process | `PreProcessNode` | Caller-contract validation, instruction-override screen | VERIFIED_EXTERNAL |
| main | `InvestmentKnowledgeGraphNode` | Wraps inner domain workflow | ANONYMOUS |
| post_process | `PostProcessNode` | Release-invariant output gate | ANONYMOUS |
| finalize | `FinalizeNode` (default) | Response metadata, timing | — |

### Inner Domain Nodes (all `TrustLevel.ANONYMOUS`)

| Node key | Class | Responsibility |
|----------|-------|---------------|
| `query_normalize` | `QueryNormalizeNode` | Deserialize the request envelope, normalize query text |
| `intent_classify` | `InvestorIntentClassifyNode` | Classify investor intent (4 categories) |
| `kb_retrieve` | `ProductKBRetrieveNode` | Retrieve from investment product KB (allowlisted selector, audited) |
| `plain_answer` | `PlainLanguageAnswerNode` | Synthesize plain-language answer |
| `suitability_gate` | `SuitabilityGateNode` | Append hardcoded 金商法 disclaimer |
| `tts_render` | `TTSRenderNode` | Optional TTS audio rendering |
| `output_format` | `OutputFormatNode` | Final formatting + credential scan |

## Configuration

`config/agent.yaml` is the flat static manifest (identity, entry point,
`requires.secrets: []` / `requires.extras: []` — this template constructs no
external clients and requires no secrets). Runtime parameters live in
`config/config.yaml` and are passed to the graph constructor (the standalone
server loads the file itself, mirroring the platform registry):

| Key | Consumer | Effect |
|---|---|---|
| `max_retry` | outer graph (framework retry loop) | Bounded retries on RETRY status |
| `domain_kb_path` | inner pipeline (seeded default) | KB selector when the caller does not supply one |
| `tts_summary_enabled` | inner pipeline (seeded default) | TTS default when the caller does not supply the flag |

Precedence for the two domain keys: per-request `input_context` value >
declared `config/config.yaml` value > literal in-code default. PreProcessNode
leaves omitted fields unset, the request envelope carries only
caller-supplied values, and `_extra_initial_state()` seeds the declared
values into the inner state — so a declared default genuinely reaches the
pipeline instead of being shadowed by hardcoded literals.

## Data Flow

### Outer State Fields (src/schemas/state.py)

| Field | Type | Set by | Description |
|-------|------|--------|-------------|
| `user_input` | `str` | caller | Raw user query |
| `validated_input` | `str` | PreProcessNode | Validated query |
| `tts_summary_enabled` | `bool` | PreProcessNode (only when supplied) | From input_context |
| `domain_kb_path` | `str` | PreProcessNode (only when supplied) | From input_context |
| `enriched_context` | `dict` | PreProcessNode | Channel metadata (inert identifier) |
| `result` | `str` | InvestmentKnowledgeGraphNode | Inner graph output |
| `formatted_output` | `str` | PostProcessNode | Final gated output |

### Inner State Fields (propagate within InvestmentWorkflowGraph)

| Field | Set by | Description |
|-------|--------|-------------|
| `normalized_query` | QueryNormalizeNode | Whitespace-normalized query |
| `intent` | InvestorIntentClassifyNode | One of: product_info, risk_query, suitability_check, general_education |
| `intent_metadata` | InvestorIntentClassifyNode | Classification scores + confidence (JSON string) |
| `retrieved_documents` | ProductKBRetrieveNode | Top KB documents (JSON string) |
| `retrieval_score` | ProductKBRetrieveNode | Top document similarity score |
| `answer_text` | PlainLanguageAnswerNode, SuitabilityGateNode | Answer (with disclaimer appended) |
| `suitability_disclaimer` | SuitabilityGateNode | Hardcoded 金商法 disclaimer |
| `tts_audio_url` | TTSRenderNode (optional) | Audio URL if TTS enabled |
| `formatted_output` | OutputFormatNode | Structured final output |

### Input Propagation (outer → inner)

`InvestmentKnowledgeGraphNode.extract_input()` JSON-encodes the query plus
only the per-request config fields the caller actually supplied:

```json
{"query": "<validated_input>", "tts_summary_enabled": true}
```

`QueryNormalizeNode` deserializes this and applies the envelope values over
the seeded declared defaults.

## Security Design

### Input boundary (PreProcessNode — owns the caller contract)

Every caller field is validated against explicit bounds and fails CLOSED;
rejected values are never echoed (errors name the field, not the value).

| Caller field | Bound |
|---|---|
| `user_input` | non-empty string, ≤ 4000 characters, instruction-override screen |
| `input_context.tts_summary_enabled` | strict boolean (coercions such as `1` / `"true"` refused) |
| `input_context.domain_kb_path` | `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` (no dots/slashes — path traversal) |
| `input_context.channel` | inert identifier `^[a-z0-9_]{1,32}$` |
| unknown `input_context` fields | refused (count reported, names never echoed) |

The instruction-override screen (src/nodes/content_screens.py) covers
chat-template control tokens (`<\|…\|>`, `[INST]`, `<<SYS>>`) as a class plus
anchored directive phrases in English and Japanese, and runs over the raw
text and its whitespace-collapsed form. The structured channel is screened
depth-first — mapping keys included — after JSON parsing, so escape forms
cannot slip past. Anchoring is two-way: ordinary investor prose containing
the same words ("about the NISA system: how does it work?", "can I ignore
all the fees?") passes.

There are no caller-controlled numeric fields in this contract; the only
non-string field is a strict boolean, and any numeric smuggled through
`input_context` (including raw `NaN`/`Infinity` JSON literals) is refused as
an unknown field.

### Output boundary (PostProcessNode — release invariant)

1. Released answers are never empty.
2. Every released answer carries the mandated suitability disclaimer
   (re-verified at the boundary, independently of SuitabilityGateNode).
3. No credential material leaves the agent (assignment forms, bearer
   tokens, JWTs, prefixed API keys, cloud access-key IDs).

On a violation the node returns an error status and CLEARS both
output-bearing state fields — the response envelope falls back to the raw
`result` field even on an error status, so blocked text must be removed
from state, not merely flagged.

The same credential scan also runs inside the inner pipeline
(`output_format`, `kb_retrieve`) from the shared module, so the boundaries
cannot drift apart.

### Output Precision

This template renders **no monetary aggregates of its own**: the answer text
quotes the curated knowledge base — including statutory amounts such as
annual NISA contribution limits — verbatim, plus a fixed disclaimer and an
optional TTS URL. There is therefore no numeric rounding/summary grid to
enforce at the output boundary — rewriting figures would corrupt legally
accurate statutory amounts, the opposite of this template's
investor-education contract. The output invariant this template owns is the
release invariant above, enforced fail-closed on the exact text that leaves
the agent.

### Audit logging

All nodes emit trace events with reason codes, counts, and identifiers only —
never caller query text, answer text, or rejected values.

## 金融商品取引法 Compliance

The `SuitabilityGateNode` appends the mandatory suitability disclaimer to
**every answer**. The disclaimer text is the module-level constant
`SUITABILITY_DISCLAIMER` and:

- Is NOT configurable via the manifest, `config/config.yaml`,
  `input_context`, or any runtime flag
- Is NOT overridable by any caller
- Cannot be disabled by setting `tts_summary_enabled=False` or any other feature flag
- Is independently re-verified at the output boundary: an answer without the
  disclaimer is never released

## Intent Classification

| Intent | Triggers | KB strategy |
|--------|----------|-------------|
| `product_info` | 投資信託, NISA, ETF, "とは", "説明" | Product factsheet docs |
| `risk_query` | リスク, 元本割れ, 価格変動, 損失 | Risk explanation docs |
| `suitability_check` | 向いている, 初心者, おすすめ, 選び方 | Suitability docs |
| `general_education` | default | Entry-level education docs |

## TTSRender (Optional)

Enabled per request via `input_context.tts_summary_enabled=true`, or by
default via `tts_summary_enabled: true` in `config/config.yaml`. The inner
graph routes to `TTSRenderNode` via the conditional edge after
`suitability_gate`. Disabled by default. The bundled implementation returns a
deterministic hash-based placeholder URL; production deployments replace it
with a real TTS provider call.

## Files

```
src/
  schemas/state.py                      State (TypedDict)
  nodes/
    content_screens.py                  Shared screens (injection, credentials, identifier bounds)
    pre_process_node.py                 Input boundary (VERIFIED_EXTERNAL)
    post_process_node.py                Output boundary (release invariant)
    query_normalize_node.py             Inner: normalize query
    investor_intent_classify_node.py    Inner: classify intent
    product_kb_retrieve_node.py         Inner: retrieve KB docs
    plain_language_answer_node.py       Inner: generate answer
    suitability_gate_node.py            Inner: hardcoded 金商法 disclaimer
    tts_render_node.py                  Inner: optional TTS
    output_format_node.py               Inner: format output
  graph/
    graph.py                            Outer graph (InvestmentKnowledgeQAAgent)
    domain_workflow_graph.py            Inner workflow (InvestmentWorkflowGraph)
  api/server.py                         FastAPI entry point (Bearer boundary, size cap)
config/agent.yaml                       Static manifest (flat; class: src.graph.graph.InvestmentKnowledgeQAAgent)
config/config.yaml                      Runtime parameters (max_retry, domain defaults)
```
