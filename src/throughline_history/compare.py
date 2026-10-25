"""Compare independent signings of the same items with what was finally kept.

For learn.iddn.uk: several people work through the same proposed items, each on a
branch of their own, and their decisions are set beside each other and beside what
the graph's main version finally holds. Pure: the caller supplies the files of each
version as {path: text}; nothing here reads git or the network.

A decision is read from the files, never from who someone is: ``signed`` where an
attempt added a signature, ``rejected`` where it moved the item to the graph's
invalidated status (``[status.roles] invalidated`` in throughline.toml), ``other``
where it moved the status anywhere else, and ``undecided`` where it did neither.
"""
from __future__ import annotations

import tomllib
from typing import Mapping

from .derive import SCHEMA_VERSION, _signature_key, _view, item_uid, under

Files = Mapping[str, str]

_DEFAULT_INVALIDATED = "rejected"


def _config(files: Files, root: str) -> dict:
    name = f"{root.strip('/')}/throughline.toml" if root.strip("/") not in ("", ".") else "throughline.toml"
    text = files.get(name)
    if not text:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def _items(files: Files, root: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path, text in files.items():
        if not under(root, path) or item_uid(path) is None or text is None:
            continue
        v = _view(text)
        if v is not None:
            out[v["uid"]] = v
    return out


def _decision(base: dict, now: dict | None, invalidated: str) -> dict:
    if now is None:
        return {"decision": "removed"}
    had = {_signature_key(s) for s in base["signatures"]}
    new = [s for s in now["signatures"] if _signature_key(s) not in had]
    out = {"status": now["status"]}
    if new:
        out.update(decision="signed", by=sorted({s.get("by") for s in new if s.get("by")}),
                   roles=sorted({s["role"] for s in new if s.get("role")}) or None)
    elif now["status"] != base["status"]:
        out["decision"] = "rejected" if now["status"] == invalidated else "other"
        reason = now["attrs"].get("invalidated_reason")
        if isinstance(reason, str) and reason:
            out["reason"] = reason
    else:
        out["decision"] = "undecided"
    return {k: v for k, v in out.items() if v is not None}


def compare(base: Files, attempts: Mapping[str, Files], final: Files | None = None, root: str = "") -> dict:
    """Each item of ``base`` that waited for a decision there, with each attempt's
    decision on it and, where ``final`` is given, the decision ``final`` holds and
    whether each attempt agreed with it. An item that already carried every
    decision it was going to get in ``base`` (ratified, rejected) is left out."""
    cfg = _config(base, root)
    roles = (cfg.get("status") or {}).get("roles") or {}
    invalidated = roles.get("invalidated", _DEFAULT_INVALIDATED)
    settled = {roles.get("ratified", "ratified"), invalidated, roles.get("tombstone", "deleted")}
    was = _items(base, root)
    tried = {name: _items(files, root) for name, files in attempts.items()}
    kept = _items(final, root) if final is not None else None
    rows = []
    totals = {name: {"decided": 0, "agreed": 0} for name in attempts}
    for uid in sorted(was):
        b = was[uid]
        if b["status"] in settled:
            continue
        row = {"uid": uid, "type": b["type"], "title": b["title"], "status": b["status"], "attempts": {}}
        if kept is not None:
            row["final"] = _decision(b, kept.get(uid), invalidated)
        for name, items in tried.items():
            d = _decision(b, items.get(uid), invalidated)
            if kept is not None and d["decision"] != "undecided":
                d["agrees"] = d["decision"] == row["final"]["decision"]
                totals[name]["decided"] += 1
                totals[name]["agreed"] += 1 if d["agrees"] else 0
            elif d["decision"] != "undecided":
                totals[name]["decided"] += 1
            row["attempts"][name] = d
        rows.append(row)
    return {"schemaVersion": SCHEMA_VERSION, "invalidated": invalidated, "items": rows,
            "attempts": [{"name": n, **t} for n, t in totals.items()]}


__all__ = ["compare"]
