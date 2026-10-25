"""Feed derive and compare from a local checkout, for tl-history.

The one module here that reads git, and so the one a browser host never imports:
there, the page fetches the same commits from GitHub and calls derive itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .derive import Commit, item_uid, under

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
    # --first-parent walks the line main itself took and diffs a merge against its
    # first parent, so a branch merged by a merge commit arrives as that one commit,
    # and the branch's own commits, which main never stood at, are not replayed.
    log = _git(top, "log", "--reverse", "--first-parent", "--diff-merges=first-parent", ref,
               f"--format={_REC}%H{_SEP}%an{_SEP}%aI{_SEP}%s", "--name-only", "--", *spec)
    for record in log.split(_REC)[1:]:
        head, _, names = record.partition("\n")
        sha, author, at, subject = head.split(_SEP, 3)
        changed = {}
        for name in names.splitlines():
            name = name.strip()
            if name and under(root, name) and item_uid(name):
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
