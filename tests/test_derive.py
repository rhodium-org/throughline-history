import subprocess

import pytest

from throughline_history import EVENT_KINDS, SCHEMA_VERSION, derive, summarise
from helpers import ROLES, TOML, commit, item, signed

ADA = {"by": "Ada Lovelace", "id": "github:ada", "fingerprint": "sha256:aaa"}


def kinds(history):
    return [(e["kind"], e["uid"]) for e in history.events]


def test_each_kind_of_change_is_one_event(tmp_path):
    """REQ-0001: creation, amendment, status, link and unlink, each read from
    the files a commit changed (TEST-0001)."""
    h = derive([
        (commit(1), {"idd/requirements/REQ-0001.yml": item("REQ-0001")}),
        (commit(2), {"idd/requirements/REQ-0001.yml": item("REQ-0001", text="It does two things.",
                                                          links=(("INT-0002", "derives_from"),))}),
        (commit(3), {"idd/requirements/REQ-0001.yml": item("REQ-0001", status="suspect", text="It does two things.",
                                                          links=(("INT-0002", "derives_from"),))}),
    ], root="idd")
    assert kinds(h) == [("created", "REQ-0001"), ("amended", "REQ-0001"), ("linked", "REQ-0001"),
                        ("unlinked", "REQ-0001"), ("status", "REQ-0001")]
    created, amended, linked, unlinked, status = h.events
    assert created["origin"] == "ai" and created["commit"]["author"] == "Ada Lovelace"
    assert amended["fields"] == ["text"]
    assert (linked["target"], unlinked["target"]) == ("INT-0002", "INT-0001")
    assert (status["from"], status["to"]) == ("proposed", "suspect")
    assert {e["kind"] for e in h.events} <= set(EVENT_KINDS)


def test_a_signature_is_dated_by_its_own_time_else_by_its_commit():
    """REQ-0002: format 4 records when a signature was made; earlier formats did
    not, and the commit that carried it stands in, said so (TEST-0002)."""
    h = derive([
        (commit(1), {"REQ-0001.yml": item("REQ-0001", status="ratified", legacy=ADA)}),
        (commit(2), {"REQ-0002.yml": item("REQ-0002", status="ratified",
                                          signatures=[{**ADA, "at": "2026-09-30T08:00:00Z", "role": "senior"}])}),
    ])
    first, second = [e for e in h.events if e["kind"] == "signed"]
    assert (first["at"], first["dated"]) == (commit(1).at, "commit")
    assert (second["at"], second["dated"], second["role"]) == ("2026-09-30T08:00:00Z", "signature", "senior")


def test_a_migration_rewrites_a_signature_and_does_not_make_one():
    """REQ-0003: the flat record lifted into the list by tl migrate is the same
    signature, so a history across the migration has one signing (TEST-0003)."""
    h = derive([
        (commit(1), {"REQ-0001.yml": item("REQ-0001", status="ratified", legacy=ADA)}),
        (commit(2), {"REQ-0001.yml": item("REQ-0001", status="ratified", signatures=[ADA])}),
    ])
    assert kinds(h) == [("created", "REQ-0001"), ("signed", "REQ-0001")]


def test_signing_again_and_withdrawing_are_their_own_events():
    """REQ-0004: a second signature by the same person after an amendment is
    marked again; a withdrawal names who withdrew whose signature (TEST-0004)."""
    resigned = {**ADA, "fingerprint": "sha256:bbb", "at": "2026-10-03T10:00:00Z"}
    h = derive([
        (commit(1), {"REQ-0001.yml": item("REQ-0001", status="ratified", signatures=[ADA])}),
        (commit(2), {"REQ-0001.yml": item("REQ-0001", status="ratified", text="Changed.", signatures=[ADA, resigned])}),
        (commit(3), {"REQ-0001.yml": item("REQ-0001", status="ratified", text="Changed.", signatures=[ADA, resigned],
                                          withdrawals=[{"by": "Ada Lovelace", "of": "Ada Lovelace",
                                                        "at": "2026-10-04T10:00:00Z", "reason": "too soon"}])}),
    ])
    signed = [e for e in h.events if e["kind"] == "signed"]
    assert [s.get("again") for s in signed] == [None, True]
    withdrawn = [e for e in h.events if e["kind"] == "withdrawn"]
    assert len(withdrawn) == 1 and withdrawn[0]["reason"] == "too soon" and withdrawn[0]["at"] == "2026-10-04T10:00:00Z"


def test_a_removed_file_and_a_renumbered_item():
    """REQ-0005: a file that goes is removed; one that goes while another comes
    with the same content under a new UID in the same commit is renumbered, as
    tl resolve does on a collision (TEST-0005)."""
    h = derive([
        (commit(1), {"REQ-0001.yml": item("REQ-0001"), "REQ-0002.yml": item("REQ-0002", text="Other.")}),
        (commit(2), {"REQ-0001.yml": None, "REQ-0003.yml": item("REQ-0003", title="Item REQ-0001")}),
        (commit(3), {"REQ-0002.yml": None}),
    ])
    assert kinds(h)[2:] == [("renumbered", "REQ-0003"), ("removed", "REQ-0002")]
    assert h.events[2]["from"] == "REQ-0001"


def test_only_item_files_inside_the_graph_are_read():
    """REQ-0006: files outside the graph's directory, its configuration and its
    register manifests are not items; a file that does not read as one is said
    to be unreadable rather than guessed at (TEST-0006)."""
    h = derive([(commit(1), {
        "idd/requirements/REQ-0001.yml": item("REQ-0001"),
        "idd/requirements/.register.yml": "prefix: REQ\n",
        "idd/throughline.toml": "[project]\n",
        "other/REQ-0009.yml": item("REQ-0009"),
        "idd/requirements/REQ-0002.yml": "not: [an item\n",
    })], root="idd")
    assert kinds(h) == [("created", "REQ-0001"), ("unreadable", "REQ-0002")]


def test_each_commit_carries_a_tally():
    """REQ-0007: after each commit, how many items there are, by status, and how
    many carry a signature, for a growth view (TEST-0007)."""
    h = derive([
        (commit(1, message="Start\n\nbody"), {"REQ-0001.yml": item("REQ-0001"), "REQ-0002.yml": item("REQ-0002")}),
        (commit(2), {"REQ-0001.yml": item("REQ-0001", status="ratified", signatures=[ADA])}),
    ])
    assert h.commits[0]["message"] == "Start"
    assert [(c["items"], c["byStatus"], c["signed"]) for c in h.commits] == [
        (2, {"proposed": 2}, 0), (2, {"proposed": 1, "ratified": 1}, 1)]
    assert h.to_json()["schemaVersion"] == SCHEMA_VERSION


def test_the_summary_groups_one_signer_by_their_id():
    """REQ-0008: per person, created, amended and signed; signatures that share
    an id are one person, named by the last name used (TEST-0008)."""
    h = derive([
        (commit(1, author="Grace Hopper"), {"REQ-0001.yml": item("REQ-0001"), "REQ-0002.yml": item("REQ-0002")}),
        (commit(2), {"REQ-0001.yml": item("REQ-0001", status="ratified", signatures=[{**ADA, "by": "Ada"}])}),
        (commit(3), {"REQ-0002.yml": item("REQ-0002", status="ratified", signatures=[ADA])}),
    ])
    s = summarise(h)
    ada = [p for p in s["people"] if p.get("id") == "github:ada"]
    assert len(ada) == 1 and ada[0]["signed"] == 2 and ada[0]["name"] == "Ada Lovelace"
    assert {i["uid"]: i["createdBy"] for i in s["items"]} == {"REQ-0001": "Grace Hopper", "REQ-0002": "Grace Hopper"}


def test_derive_and_compare_never_reach_for_git(monkeypatch):
    """REQ-0009: what runs in a browser tab reads no git and starts no process
    (TEST-0009)."""
    def refuse(*a, **k):
        raise AssertionError("a subprocess was started")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    from throughline_history import compare
    h = derive([(commit(1), {"REQ-0001.yml": item("REQ-0001", status="ratified", signatures=[ADA])})])
    summarise(h)
    compare({"REQ-0001.yml": item("REQ-0001")}, {"a": {"REQ-0001.yml": item("REQ-0001", status="ratified", signatures=[ADA])}})


def test_every_output_names_its_schema_version():
    """NFR-0001: derive, summarise and compare each say which shape they return,
    so a host refuses one it does not know (TEST-0013)."""
    from throughline_history import compare
    h = derive([(commit(1), {"REQ-0001.yml": item("REQ-0001")})])
    outs = [h.to_json(), summarise(h), compare({"REQ-0001.yml": item("REQ-0001")}, {})]
    assert [o["schemaVersion"] for o in outs] == [SCHEMA_VERSION] * 3



def test_an_item_meets_its_kind_only_when_its_signatures_do():
    """REQ-0013: under the graph's rules at each commit, an item is met when its
    current signatures satisfy what its kind requires (a junior's alone does not
    where a senior's is required), and unmet when they stop (TEST-0014).
    REQ-0014: an amendment that moves what a signature covered makes that
    signature stale, one event each (TEST-0015)."""
    cfg = "idd/throughline.toml"
    req = "idd/requirements/REQ-0001.yml"
    junior = ("Ada", "github:ada", "junior", "2026-10-02T10:00:00Z")
    senior = ("Bob", "github:bob", "senior", "2026-10-03T10:00:00Z")
    h = derive([
        (commit(1), {cfg: ROLES, req: item("REQ-0001")}),
        (commit(2), {req: signed("REQ-0001", [junior], ROLES, status="proposed")}),
        (commit(3), {req: signed("REQ-0001", [junior, senior], ROLES)}),
        (commit(4), {req: item("REQ-0001", status="ratified", text="It does two things.",
                               signatures=[e for e in __import__("yaml").safe_load(signed("REQ-0001", [junior, senior], ROLES))["ratifications"]])}),
    ], root="idd")
    k = [(e["kind"], e.get("by") or e.get("role")) for e in h.events if e["kind"] != "rules"]
    assert k == [("created", None), ("signed", "Ada"), ("status", None), ("signed", "Bob"), ("met", None),
                 ("amended", None), ("stale", "Ada"), ("stale", "Bob"), ("unmet", None)]
    met = next(e for e in h.events if e["kind"] == "met")
    assert {x["role"] for x in met["held"]} >= {"senior"}
    unmet = next(e for e in h.events if e["kind"] == "unmet")
    assert unmet["missing"] and unmet["commit"]["sha"] == commit(4).sha
    assert [c["met"] for c in h.commits] == [0, 0, 1, 0]


def test_a_change_of_rules_is_an_event_and_judges_again():
    """REQ-0015: a commit that changes the roles or what a kind requires is a
    rules event naming them, and every item is judged again under the new rules,
    its met or unmet events caused by them (TEST-0016)."""
    cfg = "idd/throughline.toml"
    req = "idd/requirements/REQ-0001.yml"
    h = derive([
        (commit(1), {cfg: TOML, req: signed("REQ-0001", [("Ada", "github:ada", None, None)], TOML)}),
        (commit(2), {cfg: ROLES}),
    ], root="idd")
    assert [e["kind"] for e in h.events] == ["created", "signed", "met", "rules", "unmet"]
    rules = h.events[3]
    assert rules["requires"] == {"requirement": {"roles": ["senior"], "signatures": 1}} and "senior" in rules["roles"]
    assert h.events[4]["cause"] == "rules"


def test_the_summary_carries_standing_and_roles():
    """REQ-0008: each item's standing after the last commit, and the roles each
    person signed in (TEST-0008)."""
    cfg, req = "throughline.toml", "REQ-0001.yml"
    h = derive([(commit(1), {cfg: ROLES, req: signed("REQ-0001", [("Ada", "github:ada", "junior", None)], ROLES)})])
    s = summarise(h)
    assert s["items"][0]["standing"] == {"met": False, "missing": ["a signature in the role 'senior'"],
                                         "held": [{"by": "Ada", "role": "junior"}]}
    assert next(p for p in s["people"] if p.get("id") == "github:ada")["roles"] == ["junior"]
