"""Turn the commits that touched a graph into the events of its history.

Pure: the caller supplies each commit and the item files it changed, oldest first,
and gets back what happened to each item and a tally per commit. Nothing here
reads git, the network or the clock, so the same code runs over a local checkout
(see :mod:`throughline_history.git`) and in a browser tab under Pyodide, where
the page fetches the commits itself and no server sees a token or a graph.

Items are read through throughline's own reader (``Item.from_dict``), which lifts
the flat ``ratified_*`` record of formats 1 to 3 into the signature list of
format 4, so a history that crosses the migration reads as one history: the
migration re-writes a signature, it does not make a new one.

A signature is more than a name since format 4: it records the role it was given
in, when, the fingerprint of what it covered and what it supersedes, and the
graph's configuration declares roles and what each kind of item requires
(``[ratify.roles]``, ``[ratify.requires.<type>]``). So the history follows the
configuration commit by commit and judges every item against the rules in force
at that commit, through throughline's own ``standing`` and ``is_stale``: when an
item came to meet what its kind requires, when it stopped, when an amendment left
a signature covering wording that is no longer there, and when the rules changed.
"""
from __future__ import annotations

import importlib
import re
from collections import Counter
import tomllib
from dataclasses import dataclass, field
from typing import Iterable, Mapping

import yaml

from throughline.model import Item
from throughline.schema import Schema

# throughline's package re-exports a function named signatures over its module of
# the same name, so the module is reached by its full path.
_sig = importlib.import_module("throughline.signatures")

# The shape of what derive returns. A host reads this before anything else and
# refuses a version it does not know rather than guessing at a new shape.
SCHEMA_VERSION = 1

# An item file is named for its UID: REQ-0001.yml. A register's manifest
# (.register.yml), the configuration and everything else are not items.
_ITEM_FILE = re.compile(r"(?:^|/)([A-Z][A-Z0-9]*-\d+)\.ya?ml$")

# What an amendment can touch, besides attributes, status, links and signatures.
_FIELDS = ("title", "text", "rationale", "type", "normative")

EVENT_KINDS = (
    "rules",       # the configuration's roles or signing requirements changed
    "created",     # the item's file appeared
    "removed",     # the item's file went
    "renumbered",  # in one commit a file went and one appeared with the same content under another UID
    "amended",     # title, text, rationale, type, normative or an attribute changed
    "status",      # the status moved
    "linked",      # a link was added
    "unlinked",    # a link was removed
    "signed",      # a signature was added
    "withdrawn",   # a withdrawal was recorded
    "stale",       # a signature stopped covering the item: what it signed was amended
    "met",         # the item's current signatures came to meet what its kind requires
    "unmet",       # they stopped meeting it: a signature went stale or was withdrawn, or the rules rose
    "unreadable",  # the file could not be read as an item at this commit
)


@dataclass(frozen=True)
class Commit:
    """One commit, as the host knows it. ``at`` is ISO 8601 with its offset."""

    sha: str
    author: str
    at: str
    message: str = ""
    login: str | None = None


@dataclass
class History:
    events: list[dict] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    # Each live item's standing after the last commit: met, missing, held.
    standing: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"schemaVersion": SCHEMA_VERSION, "events": self.events, "commits": self.commits}


def under(root: str, path: str) -> bool:
    """Whether ``path`` (repository-relative) lies in the graph at ``root``."""
    root = root.strip("/")
    return not root or root == "." or path == root or path.startswith(root + "/")


def item_uid(path: str) -> str | None:
    m = _ITEM_FILE.search(path)
    return m.group(1) if m else None


def _view(text: str) -> dict | None:
    """What derive compares between two versions of one item, or None when the
    text does not read as an item."""
    try:
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or "uid" not in data:
            return None
        item = Item.from_dict(data)
    except Exception:
        return None
    attrs = {k: v for k, v in (item.attrs or {}).items() if k != "origin"}
    return {
        "_item": item,
        "uid": item.uid,
        "type": item.type,
        "status": item.status,
        "title": item.title,
        "text": item.text,
        "rationale": item.rationale,
        "normative": item.normative,
        "origin": (item.attrs or {}).get("origin"),
        "attrs": attrs,
        "links": sorted({(l.target, l.type) for l in item.links}),
        "signatures": [dict(s) for s in (item.ratifications or []) if isinstance(s, dict) and s.get("by")],
        "withdrawals": [dict(w) for w in (item.withdrawals or []) if isinstance(w, dict)],
    }


def _signature_key(s: dict) -> tuple:
    # A migration rewrites the flat record as a list entry and keeps who signed and
    # the fingerprint they signed; a new signature has a new fingerprint.
    return (s.get("by"), s.get("id"), s.get("fingerprint"))


def _withdrawal_key(w: dict) -> tuple:
    return (w.get("by"), w.get("of"), w.get("at"), w.get("reason"))


def _stamp(commit: Commit) -> dict:
    out = {"sha": commit.sha, "author": commit.author, "at": commit.at}
    if commit.login:
        out["login"] = commit.login
    return out


def _event(kind: str, uid: str, commit: Commit, path: str, at: str | None = None, **detail) -> dict:
    ev = {"kind": kind, "uid": uid, "at": at or commit.at, "commit": _stamp(commit), "path": path}
    ev.update({k: v for k, v in detail.items() if v is not None})
    return ev


def _signed(s: dict, uid: str, commit: Commit, path: str, again: bool) -> dict:
    # A signature that recorded its own moment is dated by it; one from before
    # format 4 recorded none, so it is dated by the commit that carries it.
    return _event("signed", uid, commit, path, at=s.get("at"), by=s.get("by"), id=s.get("id"),
                  role=s.get("role"), supersedes=s.get("supersedes"), again=True if again else None,
                  backfilled=True if s.get("backfilled") else None,
                  dated="signature" if s.get("at") else "commit")


def _diff(before: dict | None, after: dict | None, commit: Commit, path: str, uid: str) -> list[dict]:
    if before is None and after is None:
        return []
    if before is None:
        evs = [_event("created", after["uid"], commit, path, type=after["type"], title=after["title"],
                      status=after["status"], origin=after["origin"],
                      links=[{"target": t, "type": k} for t, k in after["links"]] or None)]
        seen_people: set = set()
        for s in after["signatures"]:
            evs.append(_signed(s, after["uid"], commit, path, again=s.get("by") in seen_people))
            seen_people.add(s.get("by"))
        return evs
    if after is None:
        return [_event("removed", before["uid"], commit, path, title=before["title"], status=before["status"])]

    u = after["uid"]
    evs: list[dict] = []
    changed = [f for f in _FIELDS if before[f] != after[f]]
    keys = sorted(set(before["attrs"]) | set(after["attrs"]))
    changed += [f"attrs.{k}" for k in keys if before["attrs"].get(k) != after["attrs"].get(k)]
    if changed:
        evs.append(_event("amended", u, commit, path, fields=changed))
    if before["status"] != after["status"]:
        evs.append(_event("status", u, commit, path, **{"from": before["status"], "to": after["status"]}))
    was, now = set(before["links"]), set(after["links"])
    for t, k in sorted(now - was):
        evs.append(_event("linked", u, commit, path, target=t, type=k))
    for t, k in sorted(was - now):
        evs.append(_event("unlinked", u, commit, path, target=t, type=k))
    had = {_signature_key(s) for s in before["signatures"]}
    signers = {s.get("by") for s in before["signatures"]}
    for s in after["signatures"]:
        if _signature_key(s) not in had:
            evs.append(_signed(s, u, commit, path, again=s.get("by") in signers))
            signers.add(s.get("by"))
    had_w = {_withdrawal_key(w) for w in before["withdrawals"]}
    for w in after["withdrawals"]:
        if _withdrawal_key(w) not in had_w:
            evs.append(_event("withdrawn", u, commit, path, at=w.get("at"), by=w.get("by"),
                              of=w.get("of"), reason=w.get("reason")))
    return evs


def _same_content(a: dict, b: dict) -> bool:
    keys = ("type", "title", "text", "rationale", "normative")
    return all(a[k] == b[k] for k in keys)


def config_path(root: str) -> str:
    root = root.strip("/")
    return "throughline.toml" if root in ("", ".") else f"{root}/throughline.toml"


def _schema(text: str | None) -> tuple[Schema, dict]:
    """The rules a configuration declares, and the part of it a rules event shows:
    the roles and what each kind requires. A configuration that does not read
    leaves the default rules, one signature of anyone."""
    try:
        config = tomllib.loads(text) if text else {}
        schema = Schema.from_config(config or None)
    except Exception:
        return Schema.from_config(None), {}
    ratify = config.get("ratify") or {}
    return schema, {"roles": ratify.get("roles") or {}, "requires": ratify.get("requires") or {}}


def _standing(view: dict, schema: Schema) -> dict:
    """Where the item stands under ``schema``: whether its current signatures meet
    what its kind requires, what is still missing, and which signatures are current."""
    item = view["_item"]
    try:
        st = _sig.standing(item, schema)
        current = {_signature_key(e) for e in _sig.current(item, schema)}
        return {"met": st.met, "missing": list(st.missing), "current": current,
                "held": [{"by": e.get("by"), "role": e.get("role")} for e in st.held]}
    except Exception:
        return {"met": False, "missing": [], "current": set(), "held": []}


def _judge(before: dict | None, after: dict | None, view: dict, commit: Commit, path: str, why: str | None = None) -> list[dict]:
    """The stale, met and unmet events between two standings of one item."""
    evs: list[dict] = []
    uid = view["uid"]
    if before is not None:
        for s in view["signatures"]:
            k = _signature_key(s)
            if k in before["current"] and k not in after["current"]:
                evs.append(_event("stale", uid, commit, path, by=s.get("by"), id=s.get("id"), role=s.get("role")))
    was = bool(before and before["met"])
    if after["met"] and not was:
        evs.append(_event("met", uid, commit, path, held=after["held"], cause=why))
    elif was and not after["met"]:
        evs.append(_event("unmet", uid, commit, path, missing=after["missing"] or None, cause=why))
    return evs


class GraphTracker:
    """One graph's history, followed commit by commit: its items, their standing
    under the rules its configuration declares, and a tally after each commit.
    derive() runs one; derive_repo() runs one for each graph a repository holds."""

    def __init__(self, root: str = ""):
        self.root = root.strip("/")
        if self.root == ".":
            self.root = ""
        self.cfg = config_path(self.root)
        self.state: dict[str, dict] = {}
        self.standing: dict[str, dict] = {}
        self.schema, self.rules = _schema(None)

    def step(self, commit: Commit, changes: Mapping[str, str | None]) -> tuple[list[dict], dict]:
        """The events one commit's changes make in this graph, and the tally after it."""
        events: list[dict] = []
        created: list[tuple[int, dict]] = []
        removed: list[tuple[int, dict]] = []
        if self.cfg in changes:
            self.schema, now_rules = _schema(changes[self.cfg])
            if now_rules != self.rules:
                events.append(_event("rules", "", commit, self.cfg, roles=now_rules.get("roles") or None,
                                     requires=now_rules.get("requires") or None))
                self.rules = now_rules
                # The same signatures, judged by the new rules.
                for p_, v in sorted(self.state.items()):
                    st = _standing(v, self.schema)
                    events.extend(_judge(self.standing.get(p_), st, v, commit, p_, why="rules"))
                    self.standing[p_] = st
        for path in sorted(changes):
            if path == self.cfg or not under(self.root, path):
                continue
            uid = item_uid(path)
            if uid is None:
                continue
            text = changes[path]
            before = self.state.get(path)
            after = _view(text) if text is not None else None
            if text is not None and after is None:
                events.append(_event("unreadable", uid, commit, path))
                continue
            for ev in _diff(before, after, commit, path, uid):
                if ev["kind"] == "created":
                    created.append((len(events), after))
                elif ev["kind"] == "removed":
                    removed.append((len(events), before))
                events.append(ev)
            if after is None:
                self.state.pop(path, None)
                self.standing.pop(path, None)
            else:
                self.state[path] = after
                st = _standing(after, self.schema)
                events.extend(_judge(self.standing.get(path), st, after, commit, path))
                self.standing[path] = st
        # In one commit, a file that went and one that came with the same content
        # under another UID is one item renumbered (tl resolve does this).
        drop: set[int] = set()
        for ri, gone in removed:
            for ci, came in created:
                if ci in drop or gone["uid"] == came["uid"] or not _same_content(gone, came):
                    continue
                events[ri] = _event("renumbered", came["uid"], commit, events[ri]["path"],
                                    **{"from": gone["uid"], "title": came["title"]})
                drop.add(ci)
                break
        if drop:
            events = [e for i, e in enumerate(events) if i not in drop]
        return events, self.tally()

    def tally(self) -> dict:
        """The graph as it stands: items in all, by status and by node type; items
        signed and items meeting their kind's requirement; links by link type."""
        live = list(self.state.values())
        count = lambda keys: dict(sorted(Counter(keys).items()))
        return {
            "items": len(live),
            "byStatus": count(v["status"] for v in live),
            "byType": count(v["type"] for v in live),
            "signed": sum(1 for v in live if v["signatures"]),
            "met": sum(1 for p_ in self.state if self.standing.get(p_, {}).get("met")),
            "links": count(k for v in live for _, k in v["links"]),
        }

    def final_standing(self) -> dict:
        return {self.state[p_]["uid"]: {k: v for k, v in st.items() if k != "current"}
                for p_, st in self.standing.items() if p_ in self.state}


def derive(steps: Iterable[tuple[Commit, Mapping[str, str | None]]], root: str = "") -> History:
    """The history of the graph at ``root`` (repository-relative; '' for the
    repository's own root) from ``steps``: each a commit, oldest first, with the
    text of every file it changed, or None for a file it deleted. The graph's
    throughline.toml among them sets the rules items are judged by from that
    commit on. Files outside ``root`` and files that are neither the configuration
    nor items are ignored."""
    graph = GraphTracker(root)
    history = History()
    for commit, changes in steps:
        events, tally = graph.step(commit, changes)
        history.events.extend(events)
        history.commits.append({**_stamp(commit), "message": commit.message.splitlines()[0] if commit.message else "", **tally})
    history.standing = graph.final_standing()
    return history


def summarise(history: History) -> dict:
    """Per item and per person, from a derived history: who created each item and
    when, who has signed it, and how often each person created, amended and signed."""
    items: dict[str, dict] = {}
    people: dict[str, dict] = {}
    # A signature's id (github:login, an email) is the stable part of who signed;
    # its name is free text and changes. Signatures that share an id are one person,
    # named by the last name they signed under. Commit authors carry no id here.
    named: dict[str, str] = {}
    for ev in history.events:
        if ev["kind"] in ("signed", "withdrawn") and ev.get("id") and ev.get("by"):
            named[ev["by"]] = ev["id"]

    def person(name: str | None, ident: str | None = None) -> dict:
        key = ident or named.get(name or "") or name or "unknown"
        p = people.setdefault(key, {"name": name or "unknown", "id": ident or named.get(name or ""), "names": [],
                                    "roles": [], "created": 0, "amended": 0, "signed": 0, "withdrew": 0})
        if name and name not in p["names"]:
            p["names"].append(name)
            p["name"] = name
        return p

    for ev in history.events:
        uid = ev["uid"]
        if ev["kind"] == "created":
            items[uid] = {"uid": uid, "type": ev.get("type"), "title": ev.get("title"), "origin": ev.get("origin"),
                          "createdAt": ev["at"], "createdBy": ev["commit"]["author"], "signers": [], "status": ev.get("status")}
            person(ev["commit"]["author"])["created"] += 1
        elif ev["kind"] == "renumbered" and ev.get("from") in items:
            items[uid] = {**items.pop(ev["from"]), "uid": uid}
        elif ev["kind"] == "amended":
            person(ev["commit"]["author"])["amended"] += 1
        elif ev["kind"] == "status" and uid in items:
            items[uid]["status"] = ev["to"]
        elif ev["kind"] == "signed":
            who = person(ev.get("by"), ev.get("id"))
            who["signed"] += 1
            if ev.get("role") and ev["role"] not in who["roles"]:
                who["roles"].append(ev["role"])
            if uid in items and ev.get("by") not in items[uid]["signers"]:
                items[uid]["signers"].append(ev.get("by"))
        elif ev["kind"] == "withdrawn":
            person(ev.get("by"), ev.get("id"))["withdrew"] += 1
        elif ev["kind"] == "removed":
            items.pop(uid, None)
    for uid, it in items.items():
        st = history.standing.get(uid)
        if st is not None:
            it["standing"] = {"met": st["met"], "missing": st["missing"], "held": st["held"]}
    return {"schemaVersion": SCHEMA_VERSION, "items": list(items.values()),
            "people": [{k: v for k, v in p.items() if v is not None} for _, p in sorted(people.items())]}


__all__ = ["Commit", "History", "GraphTracker", "derive", "summarise", "under", "item_uid", "config_path", "EVENT_KINDS", "SCHEMA_VERSION"]

