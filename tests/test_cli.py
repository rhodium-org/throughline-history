import json
import subprocess

from throughline_history.cli import main
from helpers import TOML, item


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "Ada Lovelace", "GIT_AUTHOR_EMAIL": "ada@example.org",
                        "GIT_COMMITTER_NAME": "Ada Lovelace", "GIT_COMMITTER_EMAIL": "ada@example.org",
                        "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo)})


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_tl_history_reads_a_checkout_and_a_branch_merged_by_a_merge_commit(tmp_path, capsys):
    """REQ-0012: tl-history reads every commit reachable from the ref, merges
    left out, each against its own parent, so a change on a branch merged by a
    merge commit is the branch commit's, by its author; compare reads each version
    named (TEST-0012)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "idd/throughline.toml", TOML)
    write(repo, "idd/requirements/REQ-0001.yml", item("REQ-0001"))
    write(repo, "README.md", "not the graph\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "Start")
    git(repo, "tag", "start")
    git(repo, "checkout", "-q", "-b", "junior")
    write(repo, "idd/requirements/REQ-0001.yml",
          item("REQ-0001", status="ratified", signatures=[{"by": "Ada", "id": "github:ada", "fingerprint": "sha256:a"}]))
    git(repo, "commit", "-q", "-am", "Sign REQ-0001")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge junior", "junior")
    git(repo, "tag", "merged")

    assert main(["-C", str(repo / "idd"), "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [(e["kind"], e["uid"]) for e in out["events"]] == [("created", "REQ-0001"), ("status", "REQ-0001"), ("signed", "REQ-0001")]
    assert [c["message"] for c in out["commits"]] == ["Start", "Sign REQ-0001"]

    # A main-line commit dated after a branch commit, whose tree lacks the branch's
    # file, does not make that file seem to go (each commit against its own parent).
    git(repo, "checkout", "-q", "-b", "other", "main~1")
    write(repo, "idd/requirements/REQ-0002.yml", item("REQ-0002"))
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "Add REQ-0002")
    git(repo, "checkout", "-q", "main")
    write(repo, "idd/requirements/REQ-0001.yml",
          item("REQ-0001", status="ratified", text="Changed.", signatures=[{"by": "Ada", "id": "github:ada", "fingerprint": "sha256:a"}]))
    git(repo, "commit", "-q", "-am", "Amend REQ-0001")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge other", "other")
    write(repo, "idd/throughline.toml", TOML + '\n[ratify.roles]\nsenior = ["github:bob"]\n')
    git(repo, "commit", "-q", "-am", "Declare a senior")
    assert main(["-C", str(repo / "idd"), "--format", "json"]) == 0
    later = json.loads(capsys.readouterr().out)
    assert [e["roles"] for e in later["events"] if e["kind"] == "rules"] == [{"senior": ["github:bob"]}]
    assert [e["kind"] for e in later["events"] if e["uid"] == "REQ-0002"] == ["created"]

    assert main(["compare", "-C", str(repo / "idd"), "--base", "start", "--final", "merged", "--format", "json", "junior=junior"]) == 0
    cmp = json.loads(capsys.readouterr().out)
    j = cmp["items"][0]["attempts"]["junior"]
    assert {k: j[k] for k in ("status", "decision", "by", "agrees")} == {"status": "ratified", "decision": "signed", "by": ["Ada"], "agrees": True}


def test_outside_a_repository_it_says_so_and_exits_2(tmp_path, capsys):
    """REQ-0012: a directory that is not in a git repository is a usage error,
    said in a line (TEST-0012)."""
    assert main(["-C", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("tl-history: ")
