"""Property 3 of the pre-registered substrate: an atom is verified against the far-side artifact it
describes, not against another atom that agrees. ``verify_atom`` reads the mounted artifact;
``audit_verified`` re-checks every VERIFIED atom's recorded hash against the artifact as it is now."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from individuation_agent.artifacts import ArtifactMount, audit_verified, sha256_of, verify_atom
from individuation_agent.models import IdentityAtom
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
REF = "etc/agent/retry_policy.toml"
CONTENT = "max_retries = 5\nbackoff_ms = 2000\n"


def claim(ref=REF, excerpt="max_retries = 5", tier="REPORTED", sha=None):
    return IdentityAtom(
        id=uuid4(), made_on=NOW, made_by="agent:t", made_in="session:1", about="self.config.max_retries",
        terminal=True, tier=tier, status="live", statement="max_retries is 5", atom_kind="fact", confidence=0.6,
        artifact_ref=ref, artifact_excerpt=excerpt, artifact_sha256=sha,
    )


@pytest.fixture
def mount(tmp_path):
    root = tmp_path / "mounts"
    (root / "etc" / "agent").mkdir(parents=True)
    (root / REF).write_bytes(CONTENT.encode("utf-8"))
    return ArtifactMount(root)


@pytest.fixture
def store(tmp_path):
    return AtomStore(tmp_path / "atoms.jsonl")


def test_verify_stamps_verified_with_the_artifact_hash(store, mount):
    a = claim()
    store.append(a)
    result = verify_atom(store, a.id, mount, session_id="session:2")
    assert result.verdict == "VERIFIED"
    new = store.get(result.atom_id)
    assert new.tier == "VERIFIED"
    assert new.artifact_sha256 == sha256_of(CONTENT.encode("utf-8"))
    assert new.supersedes == a.id
    assert store.get(a.id).status == "superseded"


def test_verify_fails_when_the_excerpt_is_not_in_the_artifact(store, mount):
    a = claim(excerpt="max_retries = 2")
    store.append(a)
    result = verify_atom(store, a.id, mount, session_id="session:2")
    assert result.verdict == "FAIL"
    assert result.atom_id is None
    assert store.get(a.id).tier == "REPORTED" and store.get(a.id).status == "live"
    # the failed check is itself on the record
    checks = store.all(kind="ego.verification")
    assert len(checks) == 1 and checks[0].model_extra["verdict"] == "FAIL" and a.id in checks[0].links


def test_verify_fails_when_the_artifact_is_missing(store, mount):
    a = claim(ref="etc/agent/absent.toml")
    store.append(a)
    assert verify_atom(store, a.id, mount, session_id="session:2").verdict == "FAIL"


def test_verify_refuses_an_atom_with_no_artifact_ref(store, mount):
    a = claim(ref=None, excerpt=None)
    store.append(a)
    assert verify_atom(store, a.id, mount, session_id="session:2").verdict == "UNKNOWN"


def test_audit_reports_a_verified_atom_whose_artifact_changed(store, mount):
    a = claim()
    store.append(a)
    verified_id = verify_atom(store, a.id, mount, session_id="session:2").atom_id
    (mount.root / REF).write_bytes(b"max_retries = 7\n")
    stale = audit_verified(store, mount)
    assert [s.atom_id for s in stale] == [verified_id]
    assert stale[0].recorded_sha256 == sha256_of(CONTENT.encode("utf-8"))
    assert stale[0].current_sha256 == sha256_of(b"max_retries = 7\n")


def test_audit_is_empty_when_every_hash_still_matches(store, mount):
    a = claim()
    store.append(a)
    verify_atom(store, a.id, mount, session_id="session:2")
    assert audit_verified(store, mount) == []


def test_audit_reports_a_missing_artifact_as_stale(store, mount):
    a = claim()
    store.append(a)
    verify_atom(store, a.id, mount, session_id="session:2")
    (mount.root / REF).unlink()
    stale = audit_verified(store, mount)
    assert len(stale) == 1 and stale[0].current_sha256 is None
