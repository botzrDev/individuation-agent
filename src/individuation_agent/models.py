"""Pydantic models mirroring the six P1 JSON schemas.

The schemas in ``schemas/`` are the contract. These models exist so the
package has typed objects to pass around; ``validate_against_schema``
proves, in tests, that what they serialize still satisfies the contract.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Iterable, Literal, Union
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field
from referencing import Registry, Resource

from .schemas import SCHEMA_DIR

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

Tier = Literal["VERIFIED", "REPORTED", "INFERRED", "UNKNOWN"]
_TIER_ORDER: tuple[str, ...] = ("VERIFIED", "REPORTED", "INFERRED", "UNKNOWN")

AtomStatus = Literal["live", "superseded", "retired", "VIOLATED"]
ObligationStatus = Literal["live", "discharged", "released", "expired", "BREACHED"]
Verdict = Literal["PASS", "FAIL", "UNKNOWN"]
Archetype = Literal["Sage", "Guardian", "Harvester", "Weaver", "Trickster", "Sovereign", "Hero", "Caregiver"]
CognitiveMode = Literal["convergent", "divergent"]
Event = Literal[
    "session_start", "session_end", "role_switch", "contradiction_detected", "error_pattern_threshold", "scheduled"
]
ShadowClass = Literal["contradiction", "blind_spot", "unused_capability", "suppressed_completion"]
ProposalAction = Literal["resolve", "adopt", "revise", "defer"]
CheckKind = Literal["lint_tool", "text_forbidden", "pattern", "manual", "live_text", "cites_evidence"]


def weakest(tiers: Iterable[Tier]) -> Tier:
    """The weakest tier in the iterable (synthesis inherits the weakest input tier)."""
    idx = max(_TIER_ORDER.index(t) for t in tiers)
    return _TIER_ORDER[idx]  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #


class AtomEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: UUID
    kind: str
    made_on: datetime
    made_by: str
    made_in: str
    about: str | None = None
    links: list[UUID] = Field(default_factory=list)
    terminal: bool = False
    supersedes: UUID | None = None
    tier: Tier
    status: AtomStatus = "live"
    last_read: datetime | None = None
    expires: datetime | None = None


class Check(BaseModel):
    kind: CheckKind
    tool: str | None = None
    gate: str | None = None
    patterns: list[str] = Field(default_factory=list)
    url: str | None = None
    text: str | None = None


# --------------------------------------------------------------------------- #
# Shadow Log
# --------------------------------------------------------------------------- #


class ContradictionPayload(BaseModel):
    atom_a: UUID
    atom_b: UUID
    field: str
    detected_on: datetime
    severity: Literal["CRITICAL", "KNOWN_ABSENT", "DEBRIS", "UNSTATTABLE", "RULE_VIOLATED"]
    statement_a: str | None = None
    statement_b: str | None = None


class BlindSpotPayload(BaseModel):
    error_signature: str
    occurrences: int = Field(ge=2)
    sessions: list[str] = Field(min_length=2)
    lint_tier: Literal["STRONG", "WEAK"] | None = None


class UnusedCapabilityPayload(BaseModel):
    tool_id: str
    available_since: datetime
    never_called_in: list[str] = Field(min_length=1)


class SuppressedCompletionPayload(BaseModel):
    prompt_hash: str
    suppressed_by: str
    sample: str | None = Field(default=None, max_length=2000)
    captured_on: datetime


ShadowPayload = Union[ContradictionPayload, BlindSpotPayload, UnusedCapabilityPayload, SuppressedCompletionPayload]


class Resolution(BaseModel):
    cycle_id: str
    action: ProposalAction
    by_atom: UUID


class ShadowItem(AtomEnvelope):
    kind: str = "shadow.item"
    probe_id: UUID
    class_: ShadowClass = Field(alias="class")
    payload: ShadowPayload
    probed_in: str
    persona_id: str
    defer_count: int = Field(default=0, ge=0, le=3)
    resolution: Resolution | None = None


# --------------------------------------------------------------------------- #
# Inter-stage messages
# --------------------------------------------------------------------------- #


class S1PersonaRecognition(AtomEnvelope):
    kind: str = "cycle.s1_persona_recognition"
    cycle_id: str
    event: Event
    archetype: Archetype
    persona_id: str
    stated_as: str
    reason: str | None = None
    cognitive_mode: CognitiveMode
    capability_bounds: list[str] = Field(default_factory=list)
    context_filters: list[Check] = Field(default_factory=list)


class SourceReport(BaseModel):
    status: Literal["OK", "BLIND", "UNKNOWN"]
    count: int = Field(ge=0)


class S2ShadowProbe(AtomEnvelope):
    kind: str = "cycle.s2_shadow_probe"
    cycle_id: str
    persona_id: str
    since: datetime | None = None
    probe_ids: list[UUID] = Field(default_factory=list)
    sources: dict[str, SourceReport]


class ModelCall(BaseModel):
    base_model_id: str
    base_model_version: str
    distinct_model: bool = False


class Proposal(BaseModel):
    id: UUID
    action: ProposalAction
    target: UUID
    rationale: str
    tier: Tier
    new_atom: dict | None = None


class S3Synthesis(AtomEnvelope):
    kind: str = "cycle.s3_synthesis"
    cycle_id: str
    mode: CognitiveMode
    complement_of: str
    model_call: ModelCall | None = None
    proposals: list[Proposal] = Field(default_factory=list)


class Accepted(BaseModel):
    proposal_id: UUID
    action: ProposalAction
    appended_atom: UUID


class Rejected(BaseModel):
    proposal_id: UUID
    blocked_by: str


class Governance(BaseModel):
    constraint_check: Verdict
    obligation_check: Verdict
    reconcile: Verdict


class Stages(BaseModel):
    s1: UUID
    s2: UUID
    s3: UUID


class S4StageRecord(AtomEnvelope):
    kind: str = "self.stage_record"
    cycle_id: str
    stages: Stages
    accepted: list[Accepted] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)
    governance: Governance
    es: float | None = None
    closed_at: datetime


# --------------------------------------------------------------------------- #
# Component state atoms (Ego Core, Self-Conception State)
# --------------------------------------------------------------------------- #


class IdentityAtom(AtomEnvelope):
    """One claim in the Self-Conception State. ``about`` names what the claim is about."""

    kind: str = "self.identity_atom"
    statement: str
    atom_kind: Literal["fact", "value", "commitment", "preference", "capability"]
    confidence: float = Field(ge=0.0, le=1.0)
    # Verified-against-the-artifact (substrate property 3): the far-side object this claim is about.
    # ``artifact_ref`` is a path relative to the session's artifact mount; ``artifact_excerpt`` is the
    # text the claim rests on; ``artifact_sha256`` is stamped by ``artifacts.verify_atom`` on success.
    artifact_ref: str | None = None
    artifact_excerpt: str | None = None
    artifact_sha256: str | None = None


class ErrorAtom(AtomEnvelope):
    kind: str = "ego.error"
    error_signature: str


class ToolCallAtom(AtomEnvelope):
    kind: str = "ego.tool_call"
    tool_id: str


class ConstraintAtom(AtomEnvelope):
    """A self-imposed rule (constraints register shape). ``check`` XOR ``unchecked_because``."""

    kind: str = "archetype.constraint"
    name: str
    applies_to: str
    check: Check | None = None
    unchecked_because: str | None = None


class ObligationAtom(AtomEnvelope):
    """A promise to a counterparty (obligations register shape)."""

    kind: str = "ego.obligation"
    name: str
    owed_to: str
    obligation_status: ObligationStatus = "live"


# --------------------------------------------------------------------------- #
# Registry: kind -> model class (used by the store to rehydrate atoms)
# --------------------------------------------------------------------------- #

MODEL_BY_KIND: dict[str, type[AtomEnvelope]] = {
    "self.identity_atom": IdentityAtom,
    "ego.error": ErrorAtom,
    "ego.tool_call": ToolCallAtom,
    "archetype.constraint": ConstraintAtom,
    "ego.obligation": ObligationAtom,
    "shadow.item": ShadowItem,
    "cycle.s1_persona_recognition": S1PersonaRecognition,
    "cycle.s2_shadow_probe": S2ShadowProbe,
    "cycle.s3_synthesis": S3Synthesis,
    "self.stage_record": S4StageRecord,
}


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for path in SCHEMA_DIR.glob("*.json"):
        contents = json.loads(path.read_text("utf-8"))
        resources.append((contents["$id"], Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def to_row(atom: AtomEnvelope) -> dict:
    """The one serialization of an atom: what the store writes and what the schemas are checked against."""
    return atom.model_dump(mode="json", by_alias=True, exclude_none=True)


def validate_row(row: dict, schema_name: str) -> None:
    """Raise ``jsonschema.ValidationError`` if a raw row does not satisfy ``schemas/<schema_name>``."""
    schema = json.loads((SCHEMA_DIR / schema_name).read_text("utf-8"))
    Draft202012Validator(schema, registry=_registry()).validate(row)


def validate_against_schema(model: AtomEnvelope, schema_name: str) -> None:
    """Raise ``jsonschema.ValidationError`` if ``model``, serialized as the store writes it, fails the schema."""
    validate_row(to_row(model), schema_name)
