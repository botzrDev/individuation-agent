"""Verified against the artifact (substrate property 3).

Truth of an atom is checked against the far-side object it describes, not
against another atom that agrees. ``verify_atom`` reads the artifact the
claim names on a mount, confirms the excerpt the claim rests on is in it, and
appends a superseding copy at tier VERIFIED carrying the artifact's hash.
``audit_verified`` re-reads every VERIFIED atom's artifact and reports the
ones whose hash no longer matches; the session-close gate consumes that.

Nothing here mutates a line of the store or a byte of the mount.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from .models import AtomEnvelope, IdentityAtom
from .store import AtomStore


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ArtifactMount:
    """A directory of artifacts the session may verify claims against. Refs are relative paths under it."""

    root: Path

    def read(self, ref: str) -> bytes | None:
        path = (self.root / ref).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError:
            return None  # a ref may not escape the mount
        if not path.is_file():
            return None
        return path.read_bytes()


@dataclass(frozen=True)
class VerificationResult:
    verdict: Literal["VERIFIED", "FAIL", "UNKNOWN"]
    atom_id: UUID | None  # the VERIFIED copy on success


@dataclass(frozen=True)
class Stale:
    atom_id: UUID
    artifact_ref: str
    recorded_sha256: str
    current_sha256: str | None  # None when the artifact is gone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(store: AtomStore, atom: AtomEnvelope, verdict: str, session_id: str, sha: str | None) -> None:
    store.append(AtomEnvelope(
        id=uuid4(), kind="ego.verification", made_on=_now(), made_by=f"verify:{session_id}", made_in=session_id,
        about=getattr(atom, "artifact_ref", None), links=[atom.id], tier="VERIFIED", status="live",
        verdict=verdict, artifact_sha256=sha,
    ))


def verify_atom(store: AtomStore, atom_id: UUID, mount: ArtifactMount, session_id: str) -> VerificationResult:
    atom = store.get(atom_id)
    ref = getattr(atom, "artifact_ref", None)
    if not isinstance(atom, IdentityAtom) or not ref:
        _record(store, atom, "UNKNOWN", session_id, None)
        return VerificationResult("UNKNOWN", None)
    data = mount.read(ref)
    excerpt = atom.artifact_excerpt
    found = data is not None and (excerpt is None or excerpt.encode("utf-8") in data)
    if not found:
        _record(store, atom, "FAIL", session_id, sha256_of(data) if data is not None else None)
        return VerificationResult("FAIL", None)
    sha = sha256_of(data)
    verified = atom.model_copy(update={
        "id": uuid4(), "made_on": _now(), "made_by": f"verify:{session_id}", "made_in": session_id,
        "links": [atom.id], "terminal": False, "tier": "VERIFIED", "status": "live", "artifact_sha256": sha,
    })
    new_id = store.supersede(atom.id, verified)
    _record(store, verified, "VERIFIED", session_id, sha)
    return VerificationResult("VERIFIED", new_id)


def audit_verified(store: AtomStore, mount: ArtifactMount) -> list[Stale]:
    """Every live VERIFIED atom with a recorded artifact hash whose artifact now hashes differently or is gone."""
    stale: list[Stale] = []
    for atom in store.all(kind="self.identity_atom", status="live"):
        ref = getattr(atom, "artifact_ref", None)
        recorded = getattr(atom, "artifact_sha256", None)
        if atom.tier != "VERIFIED" or not ref or not recorded:
            continue
        data = mount.read(ref)
        current = sha256_of(data) if data is not None else None
        if current != recorded:
            stale.append(Stale(atom.id, ref, recorded, current))
    return stale
