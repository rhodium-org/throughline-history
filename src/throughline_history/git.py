"""Feed derive and compare from a local checkout, for tl-history.

The one module here that reads git, and so the one a browser host never imports:
there, the page fetches the same commits from GitHub and calls derive itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .derive import Commit, config_path, item_uid, under

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


def steps(top: Path, root: str, ref: str = "HEAD"):
    """Each commit reachable from ``ref`` that touched the graph at ``root``,
    oldest first, with the text of every item file it changed."""
    spec = [root] if root else []
    # Every commit reachable from ref that changed the graph, merges left out, each
    # carrying only what it changed against its own parent: a change is attributed to
    # the person who made it, when they made it, not to whoever merged it, and a
    # branch interleaved in time with main never makes a file seem to come and go.
    # A merge's own diff would repeat its branch's changes, so it is not read.
    log = _git(top, "log", "--reverse", "--date-order", "--no-merges", ref,
               f"--format={_REC}%H{_SEP}%an{_SEP}%aI{_SEP}%s", "--name-only", "--", *spec)
    for record in log.split(_REC)[1:]:
        head, _, names = record.partition("\n")
        sha, author, at, subject = head.split(_SEP, 3)
        changed = {}
        for name in names.splitlines():
            name = name.strip()
            # Items, and the configuration whose rules they are judged by.
            if name and under(root, name) and (item_uid(name) or name == config_path(root)):
                changed[name] = _show(top, sha, name)
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
