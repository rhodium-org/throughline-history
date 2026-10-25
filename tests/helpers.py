"""Item texts in either signature shape, for the tests."""
import yaml

from throughline_history import Commit


def item(uid, *, type="requirement", status="proposed", title=None, text="It does a thing.", origin="ai",
         links=(("INT-0001", "derives_from"),), signatures=(), legacy=None, withdrawals=(), attrs=None):
    d = {"uid": uid, "type": type, "status": status, "title": title or f"Item {uid}", "text": text,
         "normative": type != "intent"}
    if links:
        d["links"] = [{"target": t, "type": k} for t, k in links]
    a = {"origin": origin, **(attrs or {})}
    if legacy:  # the flat record of formats 1 to 3
        a.update({f"ratified_{k}": v for k, v in legacy.items()})
    d["attrs"] = a
    if signatures:
        d["ratifications"] = [dict(s) for s in signatures]
    if withdrawals:
        d["withdrawals"] = [dict(w) for w in withdrawals]
    return yaml.safe_dump(d, sort_keys=False)


def commit(n, author="Ada Lovelace", at=None, message=""):
    return Commit(sha=f"{n:040x}", author=author, at=at or f"2026-10-{n:02d}T09:00:00+00:00", message=message)


TOML = """[project]
name = "fixture"
format_version = 4

[status]
values = ["draft", "proposed", "ratified", "suspect", "rejected", "deleted"]

[status.roles]
initial = "draft"
proposed = "proposed"
ratified = "ratified"
invalidated = "rejected"
suspect = "suspect"
tombstone = "deleted"
"""
