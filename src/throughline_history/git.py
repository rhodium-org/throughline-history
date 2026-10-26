"""Feed derive and compare from a local checkout, for tl-history.

The one module here that reads git, and so the one a browser host never imports:
there, the page fetches the same commits from GitHub and calls derive itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .derive import Commit, config_path, item_uid, under

CONFIG = "throughline.toml"
MANIFEST = ".register.yml"

_SEP = "\x1f"
_REC = "\x1e"


class GitError(RuntimeError):
    pass


def _git(top: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(top), *args], check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise GitError("git is not installed") from e
    except subprocess.CalledProcessError as e:
        raise GitError((e.stderr or "").strip() or f"git {' '.join(args)} failed") from e
    return done.stdout


def top_of(path: str | Path) -> Path:
    return Path(_git(Path(path), "rev-parse", "--show-toplevel").strip())


def graph_root(path: str | Path) -> tuple[Path, str]:
    """The repository holding ``path`` and the graph's directory within it."""
    here = Path(path).resolve()
    top = top_of(here)
    rel = here.relative_to(top.resolve()).as_posix()
    return top, "" if rel == "." else rel


def _show(top: Path, sha: str, path: str) -> str | None:
    try:
        return _git(top, "show", f"{sha}:{path}")
    except GitError:
        return None


def _records(top: Path, ref: str, spec: list[str]):
    """Each commit reachable from ``ref`` that changed a path in ``spec``, oldest
    first, with every path it changed against any of its parents.

    Merges are read too, against each parent (-m): a change a branch made arrives
    at the merge with the text the branch commit already gave it, and derive sees
    nothing new; what the merge itself changed, a resolution, a rename or a file
    it dropped, is the merge's own change. --no-renames: a moved file is its old
    path going and its new one coming."""
    log = _git(top, "log", "--reverse", "--date-order", "-m", "--no-renames", ref,
               f"--format={_REC}%H{_SEP}%an{_SEP}%aI{_SEP}%s", "--name-only", "--", *spec)
    order: list[str] = []
    seen: dict[str, tuple[str, str, str, set[str]]] = {}
    for record in log.split(_REC)[1:]:
        head, _, names = record.partition("\n")
        sha, author, at, subject = head.split(_SEP, 3)
        if sha not in seen:
            order.append(sha)
            seen[sha] = (author, at, subject, set())
        seen[sha][3].update(n.strip() for n in names.splitlines() if n.strip())
    for sha in order:
        author, at, subject, names = seen[sha]
        yield sha, author, at, subject, sorted(names)


def steps(top: Path, root: str, ref: str = "HEAD"):
    """Each commit reachable from ``ref`` that changed the graph at ``root``,
    oldest first, with the text it gives every item file and the configuration it
    changed against any of its parents."""
    for sha, author, at, subject, names in _records(top, ref, [root] if root else []):
        changed = {n: _show(top, sha, n) for n in names
                   if under(root, n) and (item_uid(n) or n == config_path(root))}
        if changed:
            yield Commit(sha=sha, author=author, at=at, message=subject), changed


def files_at(top: Path, root: str, ref: str) -> dict[str, str]:
    """Every file of the graph at ``root`` as it stands at ``ref``."""
    spec = [root] if root else []
    names = _git(top, "ls-tree", "-r", "--name-only", ref, "--", *spec).splitlines()
    out = {}
    for name in names:
        if name.endswith("throughline.toml") or item_uid(name):
            text = _show(top, ref, name)
            if text is not None:
                out[name] = text
    return out


def _graph_file(name: str) -> bool:
    """A file the repository reader follows: a configuration, a register's
    manifest, or an item named for its UID."""
    base = name.rsplit("/", 1)[-1]
    return base in (CONFIG, MANIFEST) or item_uid(name) is not None


def repo_steps(top: Path, ref: str = "HEAD"):
    """Every commit reachable from ``ref`` that changed a graph file anywhere in
    the repository, oldest first, read as steps() reads one graph's."""
    for sha, author, at, subject, names in _records(top, ref, ["*" + CONFIG, "*" + MANIFEST, "*.yml", "*.yaml"]):
        changed = {n: _show(top, sha, n) for n in names if _graph_file(n) and "/node_modules/" not in "/" + n}
        if changed:
            yield Commit(sha=sha, author=author, at=at, message=subject), changed
