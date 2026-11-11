# individuation-agent (P2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable, documented Python package that executes the four-stage individuation cycle as a LangGraph graph over an append-only atom store, producing the S1–S4 messages exactly as the P1 schemas define them.

**Architecture:** Pydantic models mirror the six P1 JSON schemas and are validated against them in tests. An append-only JSONL `AtomStore` is the only persistence; nothing is edited in place. The cycle is a `StateGraph` with four nodes (S1 recognize → S2 probe → S3 synthesize → S4 reorganize); Shadow detectors and the governance filter are plain Python behind small Protocols so the graph stays readable. The LLM is reached only in S3, through `langchain_core.language_models.BaseChatModel`, so tests run on a fake model and never call a provider.

**Tech Stack:** Python 3.12, uv, pydantic 2.13, jsonschema 4.26, langgraph 1.2.19, langchain-core 1.7.4, langchain-anthropic 1.7.9, pytest.

**Spec:** the P1 formalization folder of the paper's working directory (not in this repository) - `01-component-specs.md`, `02-cycle-pseudocode.md`, `03-metrics.md`, `04-schemas/*.json`, `00-substrate-snapshot.md`. The schemas are copied verbatim into `schemas/` in this repo (Task 1) and are the contract.

## Global Constraints

- Repo: `github.com/botzrDev/individuation-agent`, **private** until cross-model review passes (the pre-submission gate issue). Never flip visibility in this plan.
- Pins: `langgraph==1.2.19`, `langchain-core==1.7.4`, `langchain-anthropic==1.7.9`, `pydantic>=2.13,<3`, `jsonschema>=4.26,<5`. Python `>=3.12`.
- Append-only: no function in the package may rewrite or delete a line of an atom file. A change is a new atom whose `supersedes` names the old one.
- Every atom carries `tier` ∈ {VERIFIED, REPORTED, INFERRED, UNKNOWN} and `status`. S3 proposals inherit the weakest input tier (order VERIFIED > REPORTED > INFERRED > UNKNOWN).
- Silent detectors are never clean: a detector that cannot see reports `BLIND`; one that crashes reports `UNKNOWN`. Governance verdicts likewise: a crash is `UNKNOWN`, never `PASS`.
- `check` vocabulary is the constraints register's: kinds `lint_tool | text_forbidden | pattern | manual | live_text`. No new expression language.
- `defer_count` on a ShadowItem maxes at 3; a fourth defer is a schema violation and the S4 node must reject the proposal with `blocked_by = "max_defer"`.
- Es for a cycle = `(resolved + adopted) / probed`; `None` when probed = 0. Sc is **not** computed by this package (it is the external probe battery).
- Keep out of code, docs and sample data: API key paths, counterparty names, pricing, KNOWN_ABSENT data, Linear team prefixes, hook DENY surfaces (the operator's list).
- No em dashes in any file in this repo (substrate convention; gate 7).
- Per-repo `ai-use-log.md` is maintained from the first commit (Task 1) and appended at every task's commit.
- Commit messages end with the attribution lines the session supplies.

## Review Focus

1. A ShadowItem whose `resolution.action` is `defer` at `defer_count == 3`: S4 must reject with `blocked_by="max_defer"`, not append a 4th defer. Test in Task 7.
2. S3 returns malformed JSON or a proposal targeting a `probe_id` not in S2: synthesizer must drop the proposal and record the S3 atom at tier `UNKNOWN`, not raise. Test in Task 6.
3. Two detectors where one raises: S2 must still append the other's items and mark the raiser `UNKNOWN`. Test in Task 5.
4. `AtomStore.consult()` called by the same session that wrote the atom: `last_read` must not change (recall-meter CONSULT rule). Test in Task 3.
5. A persona whose `capability_bounds` is empty: UnusedCapabilityDetector must report `BLIND` with count 0, not OK with 0. Test in Task 5.

---

### Task 1: Repository scaffold, pins, schemas, first commit

**Files:**
- Create: `pyproject.toml`, `README.md`, `ai-use-log.md`, `LICENSE` (MIT, copyright "2026 Phillip Austin Green / Botzr Research Labs"; Austin may change), `.gitignore` (Python + `.venv/` + `*.jsonl` under `runs/`), `src/individuation_agent/__init__.py`, `schemas/` (copy of the six P1 schema files, byte-identical), `tests/conftest.py`, `tests/test_schemas_load.py`
- Test: `tests/test_schemas_load.py`

**Interfaces:**
- Produces: package name `individuation_agent`; `SCHEMA_DIR: pathlib.Path` exported from `individuation_agent.schemas` (a module at `src/individuation_agent/schemas.py` that resolves `schemas/` relative to the repo root for dev installs and to package data otherwise); fixture `schema_dir` in `conftest.py`.

- [ ] **Step 1: `uv init --package individuation-agent --python 3.12` in the repository root, then set `[project]` `name="individuation-agent"`, `version="0.1.0"`, `requires-python=">=3.12"`, and the pinned dependencies from Global Constraints; dev group: `pytest>=8`, `jsonschema>=4.26,<5`**
- [ ] **Step 2: Copy the six `*.json` files from the spec's `04-schemas/` into `schemas/` and `fc`/`cmp` them against the source; they must be identical**
- [ ] **Step 3: Write `tests/test_schemas_load.py`**

```python
def test_all_six_schemas_pass_metaschema(schema_dir):
    from jsonschema import Draft202012Validator
    names = sorted(p.name for p in schema_dir.glob("*.json"))
    assert names == ["atom-envelope.schema.json", "s1-persona-recognition.schema.json",
                     "s2-shadow-probe.schema.json", "s3-synthesis.schema.json",
                     "s4-stage-record.schema.json", "shadow-item.schema.json"]
    for p in schema_dir.glob("*.json"):
        Draft202012Validator.check_schema(json.loads(p.read_text("utf-8")))
```

- [ ] **Step 4: Run `uv run pytest -q`; expected: FAIL (`schema_dir` fixture missing)**
- [ ] **Step 5: Write `src/individuation_agent/schemas.py` exporting `SCHEMA_DIR` and `tests/conftest.py` with the `schema_dir` fixture returning it**
- [ ] **Step 6: Run `uv run pytest -q`; expected: 1 passed**
- [ ] **Step 7: Write `README.md` (title, one-paragraph purpose, "status: private pre-review", install with uv, pointer to `docs/`) and `ai-use-log.md` (header: tool, model family, date; first entry: scaffold)**
- [ ] **Step 8: `git init -b main`, commit `chore: scaffold individuation-agent with pinned LangGraph stack and P1 schemas`, then `gh repo create botzrDev/individuation-agent --private --source . --push`**
- [ ] **Step 9: Verify: `gh repo view botzrDev/individuation-agent --json visibility -q .visibility` prints `PRIVATE`**

---

### Task 2: Pydantic models mirroring the schemas

**Files:**
- Create: `src/individuation_agent/models.py`, `tests/test_models.py`

**Interfaces:**
- Produces (all in `models.py`, pydantic `BaseModel`, `model_config = ConfigDict(extra="allow")` on `AtomEnvelope` only):
  - `Tier = Literal["VERIFIED","REPORTED","INFERRED","UNKNOWN"]`; `weakest(tiers: Iterable[Tier]) -> Tier`
  - `AtomStatus = Literal["live","superseded","retired","VIOLATED"]`
  - `AtomEnvelope(id: UUID, kind: str, made_on: datetime, made_by: str, made_in: str, about: str|None=None, links: list[UUID]=[], terminal: bool=False, supersedes: UUID|None=None, tier: Tier, status: AtomStatus="live", last_read: datetime|None=None, expires: datetime|None=None)`
  - `Check(kind: Literal["lint_tool","text_forbidden","pattern","manual","live_text"], tool: str|None, gate: str|None, patterns: list[str]=[], url: str|None, text: str|None)`
  - `Archetype = Literal["Sage","Guardian","Harvester","Weaver","Trickster","Sovereign","Hero","Caregiver"]`; `CognitiveMode = Literal["convergent","divergent"]`
  - `ContradictionPayload`, `BlindSpotPayload`, `UnusedCapabilityPayload`, `SuppressedCompletionPayload` with the schema's fields; `ShadowPayload = Annotated[Union[...], Field(discriminator=None)]` resolved by `class`
  - `Resolution(cycle_id: str, action: Literal["resolve","adopt","revise","defer"], by_atom: UUID)`
  - `ShadowItem(AtomEnvelope)` with `kind="shadow.item"`, `probe_id: UUID, class_: ShadowClass = Field(alias="class"), payload: ShadowPayload, probed_in: str, persona_id: str, defer_count: int = Field(ge=0, le=3), resolution: Resolution|None=None`
  - `S1PersonaRecognition(AtomEnvelope)`, `SourceReport(status: Literal["OK","BLIND","UNKNOWN"], count: int)`, `S2ShadowProbe(AtomEnvelope)`, `Proposal`, `ModelCall`, `S3Synthesis(AtomEnvelope)`, `Accepted`, `Rejected`, `Governance(constraint_check, obligation_check, reconcile: Literal["PASS","FAIL","UNKNOWN"])`, `S4StageRecord(AtomEnvelope)` with fields exactly as in the schemas (`es: float|None`).
  - `def validate_against_schema(model: AtomEnvelope, schema_name: str) -> None` that dumps with `by_alias=True, mode="json"` and runs `jsonschema.validate` with a `referencing` registry rooted at `SCHEMA_DIR` so `$ref: atom-envelope.schema.json` resolves.

- [ ] **Step 1: Write `tests/test_models.py` with one round-trip test per message type, each building a minimal valid instance and calling `validate_against_schema(inst, "<file>.schema.json")`; plus `test_weakest_tier_order()` asserting `weakest(["VERIFIED","INFERRED"]) == "INFERRED"` and `weakest(["REPORTED","UNKNOWN"]) == "UNKNOWN"`; plus `test_defer_count_above_three_rejected()` expecting `pydantic.ValidationError`; plus `test_terminal_required_when_links_empty()` asserting `links=[]` with `terminal=False` fails schema validation (the envelope's `if/then`)**
- [ ] **Step 2: Run `uv run pytest tests/test_models.py -q`; expected: FAIL (ImportError)**
- [ ] **Step 3: Implement `models.py`** (use `pydantic.Field(alias="class")` for the reserved word; serialize `UUID` and `datetime` via `mode="json"`; `weakest` is an index lookup on the tier order tuple)
- [ ] **Step 4: Run `uv run pytest -q`; expected: all pass. This exercises the cross-file `$ref` the P1 README left open; note that in `ai-use-log.md`**
- [ ] **Step 5: Commit `feat: pydantic models validated against P1 schemas`**

---

### Task 3: Append-only AtomStore

**Files:**
- Create: `src/individuation_agent/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `AtomEnvelope`, subclasses from Task 2.
- Produces: `class AtomStore` with `__init__(self, path: Path)`; `append(self, atom: AtomEnvelope) -> UUID`; `get(self, id: UUID) -> AtomEnvelope`; `all(self, kind: str|None=None, status: AtomStatus|None=None) -> list[AtomEnvelope]`; `latest(self, kind: str) -> AtomEnvelope|None`; `supersede(self, old_id: UUID, new: AtomEnvelope) -> UUID` (appends `new` with `supersedes=old_id`, then appends a copy of old with `status="superseded"` and `supersedes=old_id`; never rewrites); `consult(self, id: UUID, session_id: str) -> None` (appends a `kind="ego.consult"` atom; `get()` reflects `last_read` from the newest consult by a session other than `made_in`); `line_count(self) -> int`. Storage: one JSON object per line; the newest line for an `id` wins on read. Model class recovery: a `kind -> model` registry dict `MODEL_BY_KIND` in `models.py` (add it there in this task).

- [ ] **Step 1: Write `tests/test_store.py`**: `test_append_then_get_round_trips`; `test_file_only_grows_on_supersede` (record `line_count()` before, `supersede`, assert count grew by exactly 2 and the first line's bytes are unchanged); `test_latest_returns_newest_live_of_kind`; `test_consult_by_other_session_sets_last_read`; `test_consult_by_author_session_does_not_set_last_read` (Review Focus 4); `test_unknown_id_raises_KeyError`
- [ ] **Step 2: Run; expected: FAIL (ImportError)**
- [ ] **Step 3: Implement `store.py`** (read the file fully on each query; P2a stores are small; an index is YAGNI)
- [ ] **Step 4: Run `uv run pytest -q`; expected: all pass**
- [ ] **Step 5: Commit `feat: append-only JSONL AtomStore with supersede and consult`**

---

### Task 4: Checks, Persona Register, Archetype Table

**Files:**
- Create: `src/individuation_agent/checks.py`, `src/individuation_agent/registers.py`, `tests/test_checks.py`, `tests/test_registers.py`

**Interfaces:**
- Consumes: `Check`, `Archetype`, `CognitiveMode` (Task 2).
- Produces:
  - `checks.py`: `Verdict = Literal["PASS","FAIL","UNKNOWN"]`; `evaluate(check: Check, text: str) -> Verdict`. Semantics: `text_forbidden` → FAIL if any `patterns` regex matches `text`, else PASS; `pattern` → PASS if any matches, else FAIL; `manual` → UNKNOWN; `lint_tool` and `live_text` → UNKNOWN in P2a (documented as not wired). A regex compile error → UNKNOWN.
  - `registers.py`: `Persona(id: str, archetype: Archetype, display_name: str, system_prompt_overrides: list[str]=[], capability_bounds: list[str]=[], context_filters: list[Check]=[], cognitive_mode: CognitiveMode, switch_conditions: list[Check]=[])`; `PersonaRegister(personas: list[Persona], active: str)` with `resolve(self, archetype: Archetype) -> Persona` (first persona with that archetype; `KeyError` if none) and `from_yaml(path) -> PersonaRegister`; `ArchetypeEntry(archetype: Archetype, activation_conditions: list[Check], default_cognitive_mode: CognitiveMode)`; `ArchetypeTable(entries: list[ArchetypeEntry], default: Archetype="Sage")` with `route(self, context_text: str) -> Archetype` (first entry whose every `activation_conditions` check evaluates PASS; else `default`) and `from_yaml(path)`. Add `pyyaml>=6` to dependencies.

- [ ] **Step 1: Write `tests/test_checks.py`**: `test_text_forbidden_fails_on_match`, `test_text_forbidden_passes_when_clean`, `test_pattern_passes_on_match`, `test_manual_is_unknown`, `test_lint_tool_is_unknown_in_p2a`, `test_bad_regex_is_unknown`
- [ ] **Step 2: Write `tests/test_registers.py`**: `test_route_picks_first_fully_passing_entry` (Guardian on text containing "security policy" via `pattern`), `test_route_falls_back_to_default`, `test_resolve_by_archetype`, `test_resolve_missing_raises_KeyError`, `test_from_yaml_round_trip` using a tmp YAML with two personas
- [ ] **Step 3: Run; expected: FAIL (ImportError)**
- [ ] **Step 4: Implement `checks.py` and `registers.py`**
- [ ] **Step 5: Run `uv run pytest -q`; expected: all pass**
- [ ] **Step 6: Commit `feat: check evaluator, persona register, archetype table`**

---

### Task 5: Shadow detectors

**Files:**
- Create: `src/individuation_agent/shadow.py`, `tests/test_shadow.py`

**Interfaces:**
- Consumes: `AtomStore` (Task 3), `Persona` (Task 4), `ShadowItem` and payloads, `SourceReport` (Task 2).
- Produces: `class ShadowDetector(Protocol)` with `name: str` (one of `memory_audit | error_log | tool_registry | collective_unconscious`, matching the S2 `sources` keys) and `probe(self, store: AtomStore, persona: Persona, since: datetime|None, cycle_id: str) -> tuple[SourceReport, list[ShadowItem]]`. Built-ins:
  - `ContradictionDetector(name="memory_audit")`: two `live` atoms of kind `self.identity_atom` with equal `about` and differing `statement` → one `contradiction` item (`severity="RULE_VIOLATED"` when either atom `status=="VIOLATED"`, else `"CRITICAL"`).
  - `BlindSpotDetector(name="error_log")`: atoms of kind `ego.error` grouped by `error_signature`; a signature seen in ≥2 distinct `made_in` → one `blind_spot` item.
  - `UnusedCapabilityDetector(name="tool_registry")`: `persona.capability_bounds` minus tool ids present in `ego.tool_call` atoms since `since` → one `unused_capability` item each. Empty `capability_bounds` → `SourceReport(status="BLIND", count=0)` and no items (Review Focus 5).
  - `SuppressedCompletionDetector(name="collective_unconscious")`: P2a default returns `SourceReport(status="BLIND", count=0)`; the hook exists so P2b can wire a shadow call.
  - `run_detectors(detectors: list[ShadowDetector], store, persona, since, cycle_id) -> tuple[dict[str, SourceReport], list[ShadowItem]]`: calls each; an exception → that name gets `SourceReport(status="UNKNOWN", count=0)` and the others still run (Review Focus 3). Every item is appended to `store` by this function before returning.

- [ ] **Step 1: Write `tests/test_shadow.py`**: `test_contradiction_detected_on_conflicting_identity_atoms`, `test_no_contradiction_when_superseded`, `test_blind_spot_needs_two_sessions`, `test_unused_capability_lists_uncalled_tools`, `test_unused_capability_blind_when_no_bounds`, `test_suppressed_completion_default_is_blind`, `test_run_detectors_marks_raiser_unknown_and_continues` (a stub detector that raises), `test_run_detectors_appends_items_to_store`
- [ ] **Step 2: Run; expected: FAIL (ImportError)**
- [ ] **Step 3: Implement `shadow.py`** (identity atoms, errors and tool calls are plain `AtomEnvelope` instances with extra fields; add `IdentityAtom(kind="self.identity_atom", statement: str, atom_kind: Literal["fact","value","commitment","preference","capability"], confidence: float)`, `ErrorAtom(kind="ego.error", error_signature: str)`, `ToolCallAtom(kind="ego.tool_call", tool_id: str)` to `models.py` and register them in `MODEL_BY_KIND`)
- [ ] **Step 4: Run `uv run pytest -q`; expected: all pass**
- [ ] **Step 5: Commit `feat: shadow detectors with BLIND/UNKNOWN source reports`**

---

### Task 6: Synthesizer (S3) over a chat model

**Files:**
- Create: `src/individuation_agent/synthesis.py`, `src/individuation_agent/prompts.py`, `tests/test_synthesis.py`

**Interfaces:**
- Consumes: `ShadowItem`, `Proposal`, `S3Synthesis`, `ModelCall`, `weakest` (Task 2); `Persona` (Task 4); `langchain_core.language_models.BaseChatModel`.
- Produces: `complement_of(mode: CognitiveMode) -> CognitiveMode`; `class Synthesizer` with `__init__(self, model: BaseChatModel, base_model_id: str, base_model_version: str)` and `run(self, persona: Persona, items: list[ShadowItem], context_text: str, cycle_id: str, session_id: str) -> S3Synthesis`. Behaviour: builds one prompt from `prompts.SYNTHESIS_TEMPLATE` (asks for a JSON array of `{action, target, rationale}`), calls `model.invoke`, parses JSON; drops any proposal whose `target` is not in `items` or whose `action` is not one of the four; each kept proposal gets `tier = weakest(tier of its target item)`; if parsing fails entirely, returns an `S3Synthesis` with `proposals=[]` and envelope `tier="UNKNOWN"` (Review Focus 2); `model_call.distinct_model=False`.

- [ ] **Step 1: Write `tests/test_synthesis.py`** using `langchain_core.language_models.fake_chat_models.FakeListChatModel(responses=[...])`: `test_complement_of_flips_mode`, `test_valid_json_becomes_proposals_with_inherited_tier` (item tier REPORTED → proposal tier REPORTED), `test_unknown_target_dropped`, `test_bad_action_dropped`, `test_malformed_json_yields_empty_unknown_s3`, `test_s3_validates_against_schema` (via `validate_against_schema`)
- [ ] **Step 2: Run; expected: FAIL (ImportError)**
- [ ] **Step 3: Implement `prompts.py` (the template names the complementary mode and lists items as `probe_id: class: payload summary`) and `synthesis.py`** (strip code fences before `json.loads`; `json.JSONDecodeError` is the only caught exception)
- [ ] **Step 4: Run `uv run pytest -q`; expected: all pass**
- [ ] **Step 5: Commit `feat: S3 synthesizer over BaseChatModel with tier inheritance`**

---

### Task 7: Governance filter and S4 reorganization

**Files:**
- Create: `src/individuation_agent/governance.py`, `src/individuation_agent/reorganize.py`, `tests/test_governance.py`, `tests/test_reorganize.py`

**Interfaces:**
- Consumes: `evaluate` (Task 4), `AtomStore` (Task 3), models (Task 2), `S3Synthesis`.
- Produces:
  - `governance.py`: `ConstraintAtom(kind="archetype.constraint", name: str, applies_to: str, check: Check|None, unchecked_because: str|None)` and `ObligationAtom(kind="ego.obligation", name: str, owed_to: str, obligation_status: Literal["live","discharged","released","expired","BREACHED"])` added to `models.py` + registry; `class Governance` with `__init__(self, store: AtomStore)` and `filter(self, proposals: list[Proposal], items_by_id: dict[UUID, ShadowItem]) -> tuple[list[Accepted-like], list[Rejected], Governance]` where: `constraint_check` = FAIL if any live constraint's `check` evaluates FAIL against the proposal's `rationale`, UNKNOWN if any evaluates UNKNOWN and none FAIL, else PASS; `obligation_check` = FAIL if any live obligation is `BREACHED`, else PASS; `reconcile` = PASS (P2a stub, documented); a raised exception in any check → that verdict UNKNOWN. A proposal is rejected with `blocked_by=<constraint name>` on a FAIL, with `blocked_by="obligation:<name>"` when obligation_check FAILs (all proposals), with `blocked_by="max_defer"` when `action=="defer"` and the target's `defer_count>=3` (Review Focus 1). UNKNOWN verdicts do not reject; they are recorded.
  - `reorganize.py`: `apply(store: AtomStore, accepted: list[Proposal], items_by_id, persona_id: str, cycle_id: str, session_id: str) -> list[Accepted]`: `resolve` → append `IdentityAtom` from `proposal.new_atom` (or a minimal one from `rationale`) and supersede the two conflicting atoms; `adopt` → append `kind="persona.capability"` atom `{persona_id, tool_id}`; `revise` → append `IdentityAtom(atom_kind="value")`; `defer` → supersede the ShadowItem with a copy whose `defer_count+1` and `resolution.action="defer"`. Each returns an `Accepted(proposal_id, action, appended_atom)`.

- [ ] **Step 1: Write `tests/test_governance.py`**: `test_pass_when_no_constraints`, `test_text_forbidden_constraint_rejects_with_name`, `test_manual_constraint_records_unknown_but_does_not_reject`, `test_breached_obligation_rejects_all`, `test_fourth_defer_rejected_max_defer`, `test_check_exception_yields_unknown`
- [ ] **Step 2: Write `tests/test_reorganize.py`**: `test_resolve_supersedes_both_conflicting_atoms`, `test_adopt_appends_capability_atom`, `test_defer_increments_defer_count_via_supersede`, `test_store_only_grows`
- [ ] **Step 3: Run; expected: FAIL (ImportError)**
- [ ] **Step 4: Implement `governance.py` and `reorganize.py`**
- [ ] **Step 5: Run `uv run pytest -q`; expected: all pass**
- [ ] **Step 6: Commit `feat: governance filter and S4 reorganization, append-only`**

---

### Task 8: The LangGraph cycle

**Files:**
- Create: `src/individuation_agent/graph.py`, `src/individuation_agent/agent.py`, `tests/test_graph.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `graph.py`: `class CycleState(TypedDict, total=False)` with keys `event, cycle_id, session_id, context_text, persona, s1, items, sources, s2, s3, accepted, rejected, governance, s4`; node functions `recognize`, `probe`, `synthesize`, `reorganize` each `(state: CycleState, config) -> dict`; `build_graph(deps: CycleDeps) -> CompiledStateGraph` using `StateGraph(CycleState)`, `START -> recognize -> probe -> synthesize -> reorganize -> END`. `CycleDeps` is a dataclass: `store, persona_register, archetype_table, detectors, synthesizer, governance, session_id, made_by`.
  - `agent.py`: `class IndividuationAgent` with `__init__(self, deps: CycleDeps)`, `run_cycle(self, event: Event, context_text: str) -> S4StageRecord` where `Event = Literal["session_start","session_end","role_switch","contradiction_detected","error_pattern_threshold","scheduled"]`; `should_cycle(self, event) -> bool` default policy: True for `session_start | session_end | role_switch`, otherwise True only if no cycle for that event class in this session yet. S4 computes `es` per Global Constraints and appends `S4StageRecord` to the store; S1, S2, S3 atoms are appended by their nodes.

- [ ] **Step 1: Write `tests/test_graph.py`** with a fixture building `CycleDeps` on a tmp store, two personas, a `FakeListChatModel` returning one `resolve` proposal: `test_full_cycle_appends_s1_s2_s3_s4_in_order` (kinds of the last four non-item atoms), `test_s4_validates_against_schema`, `test_es_is_resolved_plus_adopted_over_probed` (seed 2 contradictions, fake model resolves 1 → `es == 0.5`), `test_es_none_when_nothing_probed`, `test_should_cycle_rate_limits_scheduled`, `test_governance_unknown_recorded_in_s4`
- [ ] **Step 2: Run; expected: FAIL (ImportError)**
- [ ] **Step 3: Implement `graph.py` and `agent.py`** (confirm `from langgraph.graph import StateGraph, START, END` against the pinned 1.2.19; node functions return partial state dicts)
- [ ] **Step 4: Run `uv run pytest -q`; expected: all pass**
- [ ] **Step 5: Commit `feat: four-stage individuation cycle as a LangGraph StateGraph`**

---

### Task 9: Demo CLI, sample data, docs, review packet

**Files:**
- Create: `src/individuation_agent/cli.py`, `examples/personas.yaml`, `examples/archetypes.yaml`, `examples/seed_store.py`, `docs/architecture.md`, `docs/paper-mapping.md`, `docs/review-checklist.md`, `tests/test_cli.py`
- Modify: `pyproject.toml` (`[project.scripts] individuation-agent = "individuation_agent.cli:main"`), `README.md`

**Interfaces:**
- Consumes: `IndividuationAgent` (Task 8).
- Produces: `main(argv: list[str]|None=None) -> int` with subcommands `demo --store PATH [--fake]` (`--fake` uses `FakeListChatModel` with a canned resolve; otherwise `langchain_anthropic.ChatAnthropic(model="claude-sonnet-5-5")` reading `ANTHROPIC_API_KEY` from the environment) and `show --store PATH` (prints the latest S4 as JSON). Exit 0 on success, 2 on usage error.

- [ ] **Step 1: Write `tests/test_cli.py`**: `test_demo_fake_writes_s4` (runs `main(["demo","--store",tmp,"--fake"])`, asserts exit 0 and `show` prints a JSON object with `"kind": "self.stage_record"`), `test_usage_error_exit_2`
- [ ] **Step 2: Run; expected: FAIL (ImportError)**
- [ ] **Step 3: Implement `cli.py` (argparse), `examples/*.yaml` (Sage default, Guardian on `pattern: ["security", "policy"]`), `examples/seed_store.py` (two conflicting identity atoms + one unused tool)**
- [ ] **Step 4: Run `uv run pytest -q`; expected: all pass. Then `uv run individuation-agent demo --store runs/demo.jsonl --fake` and `show`; paste the S4 JSON into `ai-use-log.md` as the first demo run**
- [ ] **Step 5: Write `docs/architecture.md` (module map, the StateGraph picture, append-only rules), `docs/paper-mapping.md` (table: paper section → module → schema; the seven components and four stages; what P2a does NOT implement: `lint_tool`/`live_text` checks, reconcile precedence, suppressed-completion capture, Sc), `docs/review-checklist.md` (cross-model review rule from the pre-submission gate issue, the operator's sensitivity list, the five Review Focus items); update `README.md` with the demo command**
- [ ] **Step 6: Commit `docs: architecture, paper mapping, review checklist, demo CLI`; push; verify repo still `PRIVATE`**
- [ ] **Step 7: Comment on the P2a issue on the project board with the commit hash, test count, and the demo S4 excerpt; move the P2a issue to In Review; open the cross-model review (reviewer must not be a Claude model)**

---

## Self-review notes (Steve, 2026-11-03)

- Spec coverage: 7 components → Tasks 2, 4, 5, 7 (Anima/Animus = Task 6 synthesizer; Collective Unconscious = `SuppressedCompletionDetector` hook, thin by decision). 4 stages → Task 8. Metrics: Es in Task 8; Sc explicitly out of scope and documented in Task 9. Schemas: Task 1 copy, Task 2 validation incl. `$ref`. Substrate conventions (tier, BLIND/UNKNOWN, append-only, check vocabulary) → Global Constraints and Tasks 3–7.
- Gaps accepted for P2a and documented in `docs/paper-mapping.md`: `lint_tool`/`live_text` checks, reconcile precedence, real suppressed-completion capture. P2b wires what it needs.
- Type consistency: `Verdict` (Task 4) is the type used by `Governance` (Task 7) and `S4StageRecord.governance` (Task 2). `SourceReport` keys in Task 5 match the S2 schema's four `sources` names. `Accepted`/`Rejected` named in Task 2, used in Tasks 7–8.
- Proportion: plan is shorter than the P1 spec set and names no function bodies except where the signature leaves a choice.
