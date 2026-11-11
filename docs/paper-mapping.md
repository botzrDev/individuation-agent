# Mapping to the paper

The paper's P1 formalization lives in the vault (`individuation-paper/rebuild/P1-formalize/`). This table says where each formal object runs in this package.

## Seven components

| Paper component | P1 spec section | Here | Schema |
| -- | -- | -- | -- |
| Persona Register | 01 §1 | `registers.Persona`, `registers.PersonaRegister` | S1 carries `persona_id`, `capability_bounds`, `context_filters` |
| Ego Core | 01 §2 | session id, `since`, `ego.tool_call` / `ego.error` / `ego.consult` atoms; `IndividuationAgent.should_cycle` | |
| Shadow Log | 01 §3 | `shadow.*` detectors; `ShadowItem` atoms with four payload classes | `shadow-item.schema.json` |
| Anima/Animus | 01 §4 | `synthesis.Synthesizer`, `complement_of` | `s3-synthesis.schema.json` |
| Self-Conception State | 01 §5 | `IdentityAtom` atoms + `S4StageRecord` history | `s4-stage-record.schema.json` |
| Collective Unconscious | 01 §6 | `SuppressedCompletionDetector` hook (BLIND in P2a); `ModelCall` on S3 records base model id and version | |
| Archetype Table | 01 §7 | `registers.ArchetypeTable` with the eight-value `Archetype` enum | S1 `archetype` |

## Four stages

| Stage (Jung / CS) | P1 pseudocode | Node | Output atom |
| -- | -- | -- | -- |
| Persona Recognition / active-role resolution | 02 §2 S1 | `graph.recognize` | `cycle.s1_persona_recognition` |
| Shadow Confrontation / shadow probing | 02 §2 S2 | `graph.probe` | `cycle.s2_shadow_probe` (+ `shadow.item`s) |
| Anima/Animus Integration / complementary synthesis | 02 §2 S3 | `graph.synthesize` | `cycle.s3_synthesis` |
| Self-Reorganization / reflective self-model update | 02 §2 S4 | `graph.reorganize` | `self.stage_record` |

## Metrics

- **Es** (Shadow Probing Efficiency, exploratory): computed in `graph.reorganize` as `(resolved + adopted) / probed`, `null` when nothing was probed. Stored on S4 as `es`.
- **Sc** (Self-Coherence, confirmatory, = Paper 2's Q1 probe hit rate): **not computed here.** It is measured by the external probe battery defined in the pre-registration. This package only produces the agent whose Sc gets measured.

## What P2a does not implement (and says so)

| Gap | Where it would go | Why deferred |
| -- | -- | -- |
| `lint_tool` and `live_text` check kinds | `checks.evaluate` returns UNKNOWN | need the substrate's lint tools / network; P2b decides |
| Reconcile precedence across stores | `Governance._reconcile` returns PASS **when no ledger is wired** | closed 2026-11-05 for the lab: with a `reconcile.Ledger`, governance runs `reconcile` and the verdict is computed (see below) |
| Suppressed-completion capture (shadow call without persona overrides) | `SuppressedCompletionDetector` | needs a provider call per turn; cost decision for P2b |
| Persona `switch_conditions` enforcement | `registers.Persona.switch_conditions` is carried, not evaluated | routing is by Archetype Table in P2a |
| Component-state schemas (`PersonaRegister`, `EgoCore`, `ArchetypeTable`) | would join `schemas/` | P1 scoped schemas to inter-stage messages |
| Persona `context_filters` enforcement; constraint `applies_to` scoping | carried on S1 / on the constraint atom, not evaluated | every live constraint is applied to every proposal rationale in P2a |
| `PersonaRegister.active` updates on `role_switch` | `registers.PersonaRegister.active` is static | routing is per cycle via the Archetype Table |

## The eight substrate properties (lab closure, 2026-11-05)

Paper 2's pre-registration defines the P-agent by eight memory properties. The lab plan (`individuation-paper/rebuild/P2b-lab/00-lab-plan.md`, section 4) requires all eight to be enforced in the P-agent condition. Where each one runs:

| Property | Here | Enforced by |
| -- | -- | -- |
| Append-only decisions | `store.AtomStore` | no code path rewrites a line; `supersede` appends |
| Source-attributed atoms | envelope `made_on`, `made_by`, `made_in`, `about`; `IdentityAtom.artifact_ref` | models |
| Verified against the artifact | `artifacts.verify_atom`, `artifacts.audit_verified` over an `ArtifactMount` | a VERIFIED tier is stamped only with the artifact's hash; a failed check is an `ego.verification` atom |
| Cross-referenced | envelope `links` / `terminal`; `AtomStore(validate=True)` | the envelope schema's rule (no links means terminal) checked before every write in lab mode |
| Recall-measured | `ego.consult` rows give `last_read`; `gate.session_close_gate` flags diary | report-only, by design |
| Constraint-bound | `ConstraintAtom` with executable checks; `checks.evaluate` incl. `cites_evidence` | governance applies every live constraint; the lab's evidence rule is id-based, not a vocabulary regex |
| Freshness-gated | `gate.session_close_gate`, `gate.require_gate_pass` | fails closed: stale VERIFIED atoms downgraded, expired atoms retired, next session blocked until the report is acknowledged |
| Reconciled across stores | `reconcile.Ledger`, `reconcile.reconcile`; `Governance(ledger=...)` | precedence: ledger wins for obligation state, store wins for self-claims; every conflict in an `ego.reconcile_report` |

## Item carry-forward (how the Shadow Log stays honest across cycles)

A detector that re-finds something already open for the persona (unresolved or deferred) does not mint a new item; `run_detectors` hands back the existing live item, so `probe_id` and `defer_count` persist and the fourth defer is refused. Identity of a finding: the atom pair for a contradiction, the error signature for a blind spot, the tool id for an unused capability, the prompt hash for a suppressed completion. `P_c` therefore counts each open finding once per cycle.

**Resolved 2026-11-05 (Austin's ruling):** an open item that no detector re-finds in the current cycle is probed anyway; `run_detectors` appends every open item for the persona after the detector pass. A finding leaves the probe set only by resolution, adoption, revision or the deferral limit. The first live case-study trace (`docs/case-study/trace-refound-only.*`) ran under the earlier re-found-only behaviour and is kept for the record; `trace.*` is the run under this rule.

## Terminology for the rebuilt paper

Use the dual headings the P1 pseudocode uses: the Jungian name as the normative label, the CS name as what the code calls. The eight archetype names are unchanged from the original paper's Table 2.

## Rules documented after the cross-model review (2026-11-08)

| Rule | Where | Why |
| -- | -- | -- |
| A self-claim at tier INFERRED or UNKNOWN is a candidate for Shadow content; it becomes a Shadow item only when a detector surfaces it | paper 3.3.3; `shadow.py` | no detector emits items for low-tier self-claims alone, and one that did would push every such claim into Stage 3 each cycle under the probe-every-open-item rule |
| The reconcile verdict is PASS or UNKNOWN, never FAIL | `reconcile.ReconcileReport.unresolved`, `Governance._reconcile` | the precedence relation is total; FAIL is reserved for a partial relation |
| An S3 record with no proposals and nothing dropped is VERIFIED | `synthesis.Synthesizer.synthesize` | it asserts only that nothing was proposed, which was observed directly; proposal-bearing records inherit the weakest proposal tier, never above INFERRED |
| Agent transcriptions of a source's statement are REPORTED; the INFERRED cap is for cycle-authored claims | `lab/driver/memory.py`, `docs/review-checklist.md` | REPORTED is the tier for an unverified assertion by a source |
