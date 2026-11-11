"""Property 7 of the pre-registered substrate: the session-close gate fails closed on stale atoms
rather than silently proceeding. Stale means a VERIFIED atom whose artifact has changed, or any live
atom past its ``expires``. Unread old atoms are flagged as diary (property 5, recall-measured) but do
not fail the gate. The next session may not start until a FAIL report is acknowledged."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from individuation_agent.artifacts import ArtifactMount, verify_atom
from individuation_agent.gate import GateFailed, acknowledge, require_gate_pass, session_close_gate
from individuation_agent.models import IdentityAtom
from individuation_agent.store import AtomStore

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
REF = "etc/agent/retry_policy.toml"


def claim(made_on=NOW, ref=None, excerpt=None, expires=None, about="self.config.max_retries"):
    return IdentityAtom(
        id=uuid4(), made_on=made_on, made_by="agent:t", made_in="session:1", about=about, terminal=True,
        tier="REPORTED", status="live", statement="max_retries is 5", atom_kind="fact", confidence=0.6,
        artifact_ref=ref, artifact_excerpt=excerpt, expires=expires,
    )


@pytest.fixture
def mount(tmp_path):
    root = tmp_path / "mounts"
    (root / "etc" / "agent").mkdir(parents=True)
    (root / REF).write_bytes(b"max_retries = 5\n")
    return ArtifactMount(root)


@pytest.fixture
def store(tmp_path):
    return AtomStore(tmp_path / "atoms.jsonl")


def test_gate_passes_and_records_a_report_when_nothing_is_stale(store, mount):
    store.append(claim())
    report = session_close_gate(store, mount, session_id="session:1", now=NOW)
    assert report.status == "PASS"
    assert report.stale == [] and report.expired == []
    rec = store.get(report.atom_id)
    assert rec.kind == "ego.gate_report" and rec.model_extra["gate_status"] == "PASS"


def test_gate_fails_and_downgrades_a_verified_atom_whose_artifact_changed(store, mount):
    a = claim(ref=REF, excerpt="max_retries = 5")
    store.append(a)
    verified_id = verify_atom(store, a.id, mount, session_id="session:1").atom_id
    (mount.root / REF).write_bytes(b"max_retries = 7\n")
    report = session_close_gate(store, mount, session_id="session:1", now=NOW)
    assert report.status == "FAIL"
    assert [s.atom_id for s in report.stale] == [verified_id]
    assert store.get(verified_id).status == "superseded"
    live = [x for x in store.all(kind="self.identity_atom", status="live")]
    assert len(live) == 1 and live[0].tier == "REPORTED" and live[0].supersedes == verified_id


def test_gate_fails_on_an_expired_atom_and_retires_it(store, mount):
    a = claim(expires=NOW - timedelta(hours=1))
    store.append(a)
    report = session_close_gate(store, mount, session_id="session:1", now=NOW)
    assert report.status == "FAIL"
    assert report.expired == [a.id]
    assert store.get(a.id).status == "superseded"
    assert store.all(kind="self.identity_atom", status="retired")[0].supersedes == a.id


def test_gate_flags_unread_old_atoms_as_diary_without_failing(store, mount):
    old = claim(made_on=NOW - timedelta(days=30))
    fresh = claim(made_on=NOW - timedelta(days=1), about="self.role")
    store.append(old)
    store.append(fresh)
    report = session_close_gate(store, mount, session_id="session:1", now=NOW, diary_window=timedelta(days=14))
    assert report.status == "PASS"
    assert report.diary == [old.id]


def test_a_recently_consulted_old_atom_is_not_diary(store, mount):
    old = claim(made_on=NOW - timedelta(days=30))
    store.append(old)
    store.consult(old.id, "session:9")  # a non-author read refreshes last_read
    report = session_close_gate(store, mount, session_id="session:1", now=NOW, diary_window=timedelta(days=14))
    assert report.diary == []


def test_next_session_is_blocked_after_a_fail_until_acknowledged(store, mount):
    store.append(claim(expires=NOW - timedelta(hours=1)))
    report = session_close_gate(store, mount, session_id="session:1", now=NOW)
    with pytest.raises(GateFailed):
        require_gate_pass(store)
    acknowledge(store, report.atom_id, session_id="session:2")
    require_gate_pass(store)  # no raise


def test_require_gate_pass_with_no_report_yet_is_fine(store):
    require_gate_pass(store)
