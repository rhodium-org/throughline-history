"""A repository's graphs, followed together: when each was born, the sources it
declares, the registers and the node and link types it holds, every item's
history inside it (as derive() follows one graph), and how its links reach its
own items, its sibling graphs and other repositories.

Only what a graph records is shown. A graph is said to have been shaped by
another only where its throughline.toml says so in a [shaped_by] table; a
source is shown as what its [[sources]] entry declares. Nothing is inferred from
the order graphs appeared in, from comments, or from one graph composing
another: a graph that records no lineage has none here, and says so as
`shapedBy: null`.

Pure, like derive(): the caller supplies each commit, oldest first, with the
text of every throughline.toml, .register.yml and item file it changed, anywhere
in the repository.
"""
from __future__ import annotations

import posixpath
import tomllib
from dataclasses import dataclass, field
from typing import Iterable, Mapping

import yaml

from .derive import Commit, GraphTracker, History, _event, _stamp, item_uid, summarise

REPO_SCHEMA_VERSION = 2

CONFIG = "throughline.toml"
MANIFEST = ".register.yml"

REPO_EVENT_KINDS = (
    "graph-created",    # a throughline.toml appeared: a graph is born here
    "graph-removed",    # its throughline.toml went
    "source-declared",  # a [[sources]] entry appeared
    "source-changed",   # its ref, path, url or shaped_by changed
    "source-dropped",   # it went
    "shaped",           # the graph's [shaped_by] appeared or changed: its recorded lineage
    "unshaped",         # its [shaped_by] went
    "register-added",   # a register's .register.yml appeared
    "register-changed", # its prefix or the type it holds changed
    "register-removed", # it went
    "types-changed",    # node types or link types declared in the configuration changed
)


def _root_of_config(path: str) -> str | None:
    if path == CONFIG:
        return ""
    if path.endswith("/" + CONFIG):
        return path[: -len(CONFIG) - 1]
    return None


def _join(root: str, rel: str) -> str:
    joined = posixpath.normpath(posixpath.join(root or ".", rel))
    return "" if joined == "." else joined


def _read_config(text: str | None) -> dict | None:
    if text is None:
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def _sources(root: str, cfg: dict, graphs: set[str]) -> dict[str, dict]:
    """Each declared source by namespace, as the configuration says it, with where
    a path source lands in this repository."""
    out: dict[str, dict] = {}
    for s in cfg.get("sources") or []:
        if not isinstance(s, dict) or not s.get("namespace"):
            continue
        entry = {"namespace": s["namespace"]}
        if s.get("url"):
            entry.update(kind="external", url=s["url"], ref=s.get("ref"))
        elif s.get("path") is not None:
            landed = _join(root, str(s["path"]))
            entry.update(kind="graph" if landed in graphs else "path", path=s["path"], graph=landed)
        if s.get("subdir"):
            entry["subdir"] = s["subdir"]
        if s.get("shaped_by"):
            entry["shapedBy"] = list(s["shaped_by"]) if isinstance(s["shaped_by"], list) else [s["shaped_by"]]
        out[s["namespace"]] = entry
    return out


def _shaped_by(root: str, cfg: dict) -> dict | None:
    """The lineage the graph records, and only that: None where it records none."""
    t = cfg.get("shaped_by")
    if not isinstance(t, dict) or not t.get("graph"):
        return None
    out = {"graph": _join(root, str(t["graph"])), "declared": str(t["graph"])}
    if isinstance(t.get("registers"), dict):
        out["registers"] = {str(k): str(v) for k, v in sorted(t["registers"].items())}
    return out


def _types(cfg: dict) -> tuple[list[str], list[str]]:
    node = sorted((cfg.get("types") or {}).keys())
    links = cfg.get("links") or {}
    return node, sorted(links.get("types") or [])


def _register(text: str | None) -> dict | None:
    if text is None:
        return None
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}
    return {k: d[k] for k in ("prefix", "type", "title") if k in d}


@dataclass
class _Graph:
    root: str
    name: str
    born: dict
    tracker: GraphTracker
    cfg: dict = field(default_factory=dict)
    removed: dict | None = None
    registers: dict = field(default_factory=dict)
    history: History = field(default_factory=History)


@dataclass
class RepoHistory:
    graphs: dict[str, _Graph] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        roots = set(self.graphs)
        out = []
        for root, g in sorted(self.graphs.items()):
            node, link = _types(g.cfg)
            out.append({
                "root": root, "name": g.name, "born": g.born, "removed": g.removed,
                "shapedBy": _shaped_by(root, g.cfg),
                "sources": list(_sources(root, g.cfg, roots).values()),
                "registers": [{"dir": d, **r} for d, r in sorted(g.registers.items())],
                "types": node, "linkTypes": link,
            })
        # Lineage, explicit only: an edge exists where a graph's [shaped_by] names
        # another graph of this repository.
        lineage = [{"from": g["shapedBy"]["graph"], "to": g["root"], "registers": g["shapedBy"].get("registers", {}),
                    "known": g["shapedBy"]["graph"] in roots}
                   for g in out if g["shapedBy"]]
        return {"schemaVersion": REPO_SCHEMA_VERSION, "graphs": out, "lineage": lineage,
                "events": self.events, "commits": self.commits}

    def summary(self) -> dict:
        """Each graph's items (creator, signers, standing), and every person's
        counts across the repository's graphs."""
        items, people = {}, {}
        for root, g in self.graphs.items():
            s = summarise(g.history)
            items[root] = s["items"]
            for p in s["people"]:
                key = p.get("id") or p["name"]
                q = people.setdefault(key, {**p, "names": list(p["names"]), "roles": list(p["roles"]),
                                            "created": 0, "amended": 0, "signed": 0, "withdrew": 0, "graphs": []})
                for k in ("created", "amended", "signed", "withdrew"):
                    q[k] += p[k]
                q["names"] = sorted(set(q["names"]) | set(p["names"]))
                q["roles"] = sorted(set(q["roles"]) | set(p["roles"]))
                q["graphs"].append(root)
        return {"schemaVersion": REPO_SCHEMA_VERSION, "items": items,
                "people": [people[k] for k in sorted(people)]}


def _scope(cfg: dict, root: str, roots: set[str], target: str) -> dict:
    """Where a link's target lies: in this graph, in a sibling graph or another
    repository its configuration names, or under a namespace it does not declare."""
    if ":" not in target:
        return {"scope": "local"}
    ns = target.split(":", 1)[0]
    src = _sources(root, cfg, roots).get(ns)
    if src is None:
        return {"scope": "undeclared", "namespace": ns}
    if src.get("kind") == "external":
        return {"scope": "external", "namespace": ns, "url": src["url"], "ref": src.get("ref")}
    # The graph it reaches is `into`: an event's own `graph` is the graph it belongs to.
    return {"scope": "graph" if src.get("kind") == "graph" else "path", "namespace": ns, "into": src.get("graph")}


def derive_repo(steps: Iterable[tuple[Commit, Mapping[str, str | None]]]) -> RepoHistory:
    repo = RepoHistory()
    for commit, changes in steps:
        events: list[dict] = []
        alive = {r for r, g in repo.graphs.items() if g.removed is None}
        # 1. Graphs born, gone or reconfigured.
        for path in sorted(changes):
            root = _root_of_config(path)
            if root is None:
                continue
            cfg = _read_config(changes[path])
            g = repo.graphs.get(root)
            if cfg is not None and (g is None or g.removed is not None):
                name = ((cfg.get("project") or {}).get("name")) or (root or "(repository root)")
                g = repo.graphs[root] = _Graph(root, name, _stamp(commit), GraphTracker(root), {})
                alive.add(root)
                node, link = _types(cfg)
                events.append(_event("graph-created", "", commit, path, graph=root, name=name, types=node, linkTypes=link))
            if g is None:
                continue
            if cfg is None:
                g.removed = _stamp(commit)
                alive.discard(root)
                events.append(_event("graph-removed", "", commit, path, graph=root, name=g.name))
                continue
            before, after = _sources(root, g.cfg, alive), _sources(root, cfg, alive)
            for ns in sorted(set(before) | set(after)):
                if ns not in before:
                    events.append(_event("source-declared", "", commit, path, graph=root, namespace=ns, source=after[ns]))
                elif ns not in after:
                    events.append(_event("source-dropped", "", commit, path, graph=root, namespace=ns, source=before[ns]))
                elif before[ns] != after[ns]:
                    events.append(_event("source-changed", "", commit, path, graph=root, namespace=ns, source=after[ns],
                                         was={k: v for k, v in before[ns].items() if before[ns].get(k) != after[ns].get(k)}))
            sb, sa = _shaped_by(root, g.cfg), _shaped_by(root, cfg)
            if sa != sb:
                events.append(_event("shaped", "", commit, path, graph=root, **{"by": sa["graph"], "registers": sa.get("registers")})
                              if sa else _event("unshaped", "", commit, path, graph=root, was=sb["graph"]))
            if g.cfg:
                (nb, lb), (na, la) = _types(g.cfg), _types(cfg)
                if (nb, lb) != (na, la):
                    events.append(_event("types-changed", "", commit, path, graph=root,
                                         added=sorted(set(na) - set(nb)) or None, removed=sorted(set(nb) - set(na)) or None,
                                         linkTypesAdded=sorted(set(la) - set(lb)) or None, linkTypesRemoved=sorted(set(lb) - set(la)) or None))
            g.cfg = cfg
        # 2. Registers, and 3. items: each file belongs to the deepest live graph holding it.
        owner = lambda p: max((r for r in alive if r == "" or p.startswith(r + "/")), key=len, default=None)
        routed: dict[str, dict[str, str | None]] = {}
        for path in sorted(changes):
            if _root_of_config(path) is not None:
                r = _root_of_config(path)
                if r in alive:
                    routed.setdefault(r, {})[path] = changes[path]
                continue
            root = owner(path)
            if root is None:
                continue
            g = repo.graphs[root]
            if path.endswith("/" + MANIFEST) or path == MANIFEST:
                d = posixpath.dirname(path)
                d = d[len(root) + 1:] if root else d
                was, now = g.registers.get(d), _register(changes[path])
                if now is None and was is not None:
                    g.registers.pop(d)
                    events.append(_event("register-removed", "", commit, path, graph=root, dir=d, **was))
                elif now is not None and was is None:
                    g.registers[d] = now
                    events.append(_event("register-added", "", commit, path, graph=root, dir=d, **now))
                elif now is not None and now != was:
                    g.registers[d] = now
                    events.append(_event("register-changed", "", commit, path, graph=root, dir=d, **now,
                                         was={k: v for k, v in was.items() if was.get(k) != now.get(k)}))
            elif item_uid(path):
                routed.setdefault(root, {})[path] = changes[path]
        tallies = {}
        for root in sorted(alive):
            g = repo.graphs[root]
            evs, tally = g.tracker.step(commit, routed.get(root, {}))
            for e in evs:
                e["graph"] = root
                if e["kind"] in ("linked", "unlinked"):
                    e.update(_scope(g.cfg, root, alive, e["target"]))
            g.history.events.extend(evs)
            events.extend(evs)
            # Links by where they reach, beside the tracker's links by type.
            scopes: dict[str, int] = {}
            for v in g.tracker.state.values():
                for target, _ in v["links"]:
                    s = _scope(g.cfg, root, alive, target)
                    key = s["scope"] if s["scope"] == "local" else f'{s["scope"]}:{s.get("namespace")}'
                    scopes[key] = scopes.get(key, 0) + 1
            tally = {**tally, "linksTo": dict(sorted(scopes.items()))}
            g.history.commits.append({**_stamp(commit), "message": commit.message.splitlines()[0] if commit.message else "", **tally})
            tallies[root] = tally
        for g in repo.graphs.values():
            g.history.standing = g.tracker.final_standing()
        repo.events.extend(events)
        repo.commits.append({**_stamp(commit), "message": commit.message.splitlines()[0] if commit.message else "", "graphs": tallies})
    return repo


__all__ = ["RepoHistory", "derive_repo", "REPO_EVENT_KINDS", "REPO_SCHEMA_VERSION"]
