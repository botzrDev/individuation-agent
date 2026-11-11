"""Shadow detectors: what the active persona excludes, as Shadow Log items.

Four built-ins, one per S2 source. A detector that cannot see reports BLIND;
one that crashes is reported UNKNOWN by ``run_detectors``. Neither is ever
reported as a clean OK with zero findings.

Items carry forward: when a detector re-finds something that is already an
open item for this persona (unresolved or deferred), ``run_detectors`` hands
back the existing live item instead of minting a duplicate, so ``probe_id``
and ``defer_count`` persist across cycles. An open item that no detector
re-finds this cycle is probed anyway; it leaves the probe set only by
resolution, adoption, revision or the deferral limit.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Hashable, Protocol
from uuid import uuid4

from .models import (
    BlindSpotPayload,
    ContradictionPayload,
    IdentityAtom,
    ShadowItem,
    ShadowPayload,
    SourceReport,
    SuppressedCompletionPayload,
    Tier,
    UnusedCapabilityPayload,
    weakest,
)
from .registers import Persona
from .store import AtomStore


class ShadowDetector(Protocol):
    name: str

    def probe(
        self, store: AtomStore, persona: Persona, since: datetime | None, cycle_id: str, session_id: str
    ) -> tuple[SourceReport, list[ShadowItem]]: ...


def _item(
    name: str, class_: str, payload: ShadowPayload, persona: Persona, cycle_id: str, session_id: str, tier: Tier
) -> ShadowItem:
    return ShadowItem(
        id=uuid4(),
        made_on=datetime.now(timezone.utc),
        made_by=f"detector:{name}",
        made_in=session_id,
        terminal=True,
        tier=tier,
        status="live",
        probe_id=uuid4(),
        class_=class_,
        payload=payload,
        probed_in=cycle_id,
        persona_id=persona.id,
        defer_count=0,
    )


def identity_key(item: ShadowItem) -> Hashable:
    """What makes two Shadow items 'the same finding' for carry-forward purposes."""
    p = item.payload
    if isinstance(p, ContradictionPayload):
        return ("contradiction", frozenset({p.atom_a, p.atom_b}))
    if isinstance(p, BlindSpotPayload):
        return ("blind_spot", p.error_signature)
    if isinstance(p, UnusedCapabilityPayload):
        return ("unused_capability", p.tool_id)
    if isinstance(p, SuppressedCompletionPayload):
        return ("suppressed_completion", p.prompt_hash)
    return ("unknown", item.probe_id)


class ContradictionDetector:
    name = "memory_audit"

    def probe(self, store, persona, since, cycle_id, session_id):
        atoms = [a for a in store.all(kind="self.identity_atom") if a.status in ("live", "VIOLATED")]
        by_about: dict[str | None, list[IdentityAtom]] = defaultdict(list)
        for a in atoms:
            by_about[a.about].append(a)  # type: ignore[arg-type]
        items = []
        for about, group in by_about.items():
            if about is None:
                continue
            for a, b in combinations(group, 2):
                if a.statement != b.statement:
                    severity = "RULE_VIOLATED" if "VIOLATED" in (a.status, b.status) else "CRITICAL"
                    payload = ContradictionPayload(
                        atom_a=a.id, atom_b=b.id, field="statement",
                        detected_on=datetime.now(timezone.utc), severity=severity,
                        statement_a=a.statement, statement_b=b.statement,
                    )
                    tier = weakest([a.tier, b.tier])
                    items.append(_item(self.name, "contradiction", payload, persona, cycle_id, session_id, tier))
        return SourceReport(status="OK", count=len(items)), items


class BlindSpotDetector:
    name = "error_log"

    def probe(self, store, persona, since, cycle_id, session_id):
        """A signature is a blind spot when it has recurred across at least two sessions in the whole
        history. ``since`` only decides which signatures are looked at this cycle: those with a new
        occurrence since the last cycle. Counting only the window would make a recurrence across
        sessions invisible once cycles run every session."""
        errors = store.all(kind="ego.error")
        recent = {e.error_signature for e in errors if since is None or e.made_on >= since}  # type: ignore[attr-defined]
        by_sig: dict[str, list] = defaultdict(list)
        for e in errors:
            if e.error_signature in recent:  # type: ignore[attr-defined]
                by_sig[e.error_signature].append(e)  # type: ignore[attr-defined]
        items = []
        for sig, group in by_sig.items():
            sessions = sorted({e.made_in for e in group})
            if len(sessions) >= 2:
                payload = BlindSpotPayload(error_signature=sig, occurrences=len(group), sessions=sessions)
                items.append(_item(self.name, "blind_spot", payload, persona, cycle_id, session_id, "VERIFIED"))
        return SourceReport(status="OK", count=len(items)), items


class UnusedCapabilityDetector:
    """A bound tool is unused when it has never been called and has not been adopted into the persona."""

    name = "tool_registry"

    def probe(self, store, persona, since, cycle_id, session_id):
        if not persona.capability_bounds:
            return SourceReport(status="BLIND", count=0), []
        called = {c.tool_id for c in store.all(kind="ego.tool_call")}  # type: ignore[attr-defined]
        adopted = {
            a.model_extra.get("tool_id")
            for a in store.all(kind="persona.capability", status="live")
            if a.model_extra and a.model_extra.get("persona_id") == persona.id
        }
        items = []
        for tool_id in persona.capability_bounds:
            if tool_id in called or tool_id in adopted:
                continue
            payload = UnusedCapabilityPayload(
                tool_id=tool_id,
                available_since=since or datetime.now(timezone.utc),
                never_called_in=[session_id],
            )
            items.append(_item(self.name, "unused_capability", payload, persona, cycle_id, session_id, "VERIFIED"))
        return SourceReport(status="OK", count=len(items)), items


class SuppressedCompletionDetector:
    """P2a default: no shadow-call capture is wired, so this source is BLIND by construction."""

    name = "collective_unconscious"

    def probe(self, store, persona, since, cycle_id, session_id):
        return SourceReport(status="BLIND", count=0), []


def open_items(store: AtomStore, persona: Persona) -> dict[Hashable, ShadowItem]:
    """Live Shadow items for this persona that are unresolved or deferred, keyed by identity."""
    out: dict[Hashable, ShadowItem] = {}
    for it in store.all(kind="shadow.item", status="live"):
        assert isinstance(it, ShadowItem)
        if it.persona_id != persona.id:
            continue
        if it.resolution is None or it.resolution.action == "defer":
            out[identity_key(it)] = it
    return out


def run_detectors(
    detectors: list[ShadowDetector],
    store: AtomStore,
    persona: Persona,
    since: datetime | None,
    cycle_id: str,
    session_id: str,
) -> tuple[dict[str, SourceReport], list[ShadowItem]]:
    existing = open_items(store, persona)
    sources: dict[str, SourceReport] = {}
    items: list[ShadowItem] = []
    seen: set[Hashable] = set()
    for det in detectors:
        try:
            report, found = det.probe(store, persona, since, cycle_id, session_id)
        except Exception:
            sources[det.name] = SourceReport(status="UNKNOWN", count=0)
            continue
        sources[det.name] = report
        for it in found:
            key = identity_key(it)
            if key in seen:
                continue
            seen.add(key)
            if key in existing:
                items.append(existing[key])
            else:
                store.append(it)
                items.append(it)
    # An open finding leaves the probe set only by resolution, adoption, revision or the deferral
    # limit, never because a detector stopped seeing it (ruling 2026-11-05; P_c counts every open finding).
    for key, it in existing.items():
        if key not in seen:
            seen.add(key)
            items.append(it)
    return sources, items
