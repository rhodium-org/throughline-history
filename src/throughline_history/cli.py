"""tl-history: the history of a throughline graph, or a comparison of signings."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .compare import compare
from .derive import derive, summarise


def _line(ev: dict) -> str:
    who = ev.get("by") or ev["commit"]["author"]
    detail = {
        "created": lambda e: f'{e.get("type")} "{e.get("title")}" ({e.get("origin") or "no origin"})',
        "status": lambda e: f'{e["from"]} -> {e["to"]}',
        "amended": lambda e: ", ".join(e["fields"]),
        "linked": lambda e: f'{e["type"]} -> {e["target"]}',
        "unlinked": lambda e: f'{e["type"]} -> {e["target"]}',
        "signed": lambda e: (f'as {e["role"]}' if e.get("role") else "") + (" again" if e.get("again") else ""),
        "withdrawn": lambda e: f'of {e.get("of")}: {e.get("reason") or ""}',
        "renumbered": lambda e: f'from {e["from"]}',
    }.get(ev["kind"], lambda e: "")(ev)
    return f'{ev["at"][:19]}  {ev["commit"]["sha"][:8]}  {ev["kind"]:<10} {ev["uid"]:<10} {who}  {detail}'.rstrip()


def main(argv: list[str] | None = None) -> int:
    from .git import GitError, files_at, graph_root, steps

    # -C and --format are taken before or after the command, as people type them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-C", dest="dir", default=argparse.SUPPRESS, help="the graph's directory (holding throughline.toml)")
    common.add_argument("--format", choices=["text", "json"], default=argparse.SUPPRESS)
    p = argparse.ArgumentParser(prog="tl-history", description=__doc__, parents=[common])
    p.add_argument("--version", action="version", version=f"tl-history {__version__}")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("events", help="every event, oldest first (the default)", parents=[common])
    sub.add_parser("summary", help="per item and per person", parents=[common])
    sub.add_parser("graphs", help="every graph in the repository: sources, registers, recorded lineage", parents=[common])
    c = sub.add_parser("compare", help="independent signings beside what was kept", parents=[common])
    c.add_argument("--base", required=True, help="the version the attempts started from")
    c.add_argument("--final", help="the version that holds what was kept")
    c.add_argument("attempts", nargs="+", metavar="NAME=REF")
    a = p.parse_args(argv)
    a.dir = getattr(a, "dir", ".")
    a.format = getattr(a, "format", "text")
    try:
        top, root = graph_root(a.dir)
        if a.command == "compare":
            pairs = [s.split("=", 1) for s in a.attempts]
            if any(len(x) != 2 for x in pairs):
                p.error("each attempt is NAME=REF")
            out = compare(files_at(top, root, a.base), {n: files_at(top, root, r) for n, r in pairs},
                          files_at(top, root, a.final) if a.final else None, root)
            if a.format == "json":
                print(json.dumps(out, indent=2))
            else:
                for t in out["attempts"]:
                    print(f'{t["name"]}: {t["decided"]} decided, {t["agreed"]} agreed with the final version')
                for row in out["items"]:
                    cells = "  ".join(f'{n}={d["decision"]}' for n, d in row["attempts"].items())
                    fin = f'  final={row["final"]["decision"]}' if "final" in row else ""
                    print(f'{row["uid"]:<10} {cells}{fin}')
            return 0
        if a.command == "graphs":
            from .git import repo_steps
            from .repo import derive_repo
            rh = derive_repo(repo_steps(top))
            out = rh.to_json()
            if a.format == "json":
                print(json.dumps(out, indent=2))
            else:
                for g in out["graphs"]:
                    gone = " (removed)" if g["removed"] else ""
                    print(f'{g["root"] or "."}: {g["name"]}{gone}, born {g["born"]["at"][:10]}, '
                          f'{len(g["registers"])} registers, {len(g["types"])} node types, {len(g["linkTypes"])} link types')
                    for s in g["sources"]:
                        where = s.get("graph") if s.get("kind") != "external" else f'{s.get("url")}@{s.get("ref")}'
                        print(f'  draws on {s["namespace"]}: {s.get("kind")} {where}' + (f' (shaped by {", ".join(s["shapedBy"])})' if s.get("shapedBy") else ""))
                    print(f'  shaped by: {g["shapedBy"]["graph"]}' if g["shapedBy"] else "  shaped by: no lineage recorded")
            return 0
        history = derive(steps(top, root), root)
        if a.command == "summary":
            out = summarise(history)
            if a.format == "json":
                print(json.dumps(out, indent=2))
            else:
                for person in out["people"]:
                    print(f'{person["name"]}: created {person["created"]}, amended {person["amended"]}, signed {person["signed"]}, withdrew {person["withdrew"]}')
            return 0
        if a.format == "json":
            print(json.dumps(history.to_json(), indent=2))
        else:
            for ev in history.events:
                print(_line(ev))
        return 0
    except GitError as e:
        print(f"tl-history: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
