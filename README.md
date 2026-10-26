# throughline-history

How a [throughline](https://github.com/rhodium-org/throughline) graph came to be,
read from git: who created each item, who signed it and when, how it changed and
how the graph grew. And, for training, how several people's independent signings
of the same items compare with each other and with what was finally kept.

It is the reader behind **history.iddn.uk** and **learn.iddn.uk**. Those pages run
it in your own browser tab, under Pyodide, so no server ever sees your token or
your graph. The same functions run on your machine through `tl-history`.

```bash
pipx install throughline-history
tl-history -C idd                    # every event, oldest first
tl-history -C idd summary            # per person: created, amended, signed
tl-history graphs                    # every graph in the repository: sources, registers, recorded lineage
tl-history -C idd compare --base main~3 --final main junior=review/junior senior=review/senior
```

Add `--format json` to any of them for the data the pages use.

## As a library

```python
from throughline_history import Commit, derive, summarise, compare

history = derive([(Commit(sha, author, at, message), {path: text_or_None, ...}), ...], root="idd")
history.to_json()     # {"schemaVersion": 1, "events": [...], "commits": [...]}
summarise(history)    # per item and per person
compare(base_files, {"junior": files, "senior": files}, final_files, root="idd")
```

For a whole repository, `derive_repo` follows every graph together: when each was
born and removed, the sources it declares (a sibling graph, another path, or another
repository at a ref), its registers, node types and link types, every item inside it,
and where its links reach. A graph is shown as shaped by another only where its own
`throughline.toml` says so in a `[shaped_by]` table (the `tl:shape` skill writes one);
nothing is inferred from order, comments or composition.

```python
from throughline_history.repo import derive_repo
derive_repo(steps).to_json()   # {"schemaVersion": 2, "graphs": [...], "lineage": [...], "events": [...], "commits": [...]}
```

Every commit is read against each of its parents with its own version of each file,
merges included, so a branch's work is its commits' and what a merge itself changed
is the merge's; a moved file is its old path going and its new one coming.

`derive`, `summarise`, `compare` and `derive_repo` read only what they are given: no git, no
network, no process. The caller fetches the commits; `tl-history` does that from
a local checkout, a page does it from GitHub.

## What it reads, and what it does not

- Items are read through throughline's own reader, so every format the graph was
  ever written in reads as one history. A migration rewrites a signature; it does
  not make one.
- A signature is dated by the time it recorded (format 4) or, before that, by the
  commit that carried it, and each event says which. It carries the role it was
  given in and what it supersedes.
- Every item is judged at every commit by the rules the graph's `throughline.toml`
  declared then (`[ratify.roles]`, `[ratify.requires.<type>]`), through throughline's
  own `standing`: the history says when an item's signatures came to meet what its
  kind requires and when they stopped, when an amendment left a signature covering
  wording that is no longer there, and when the rules changed. A graph that declares
  no rules needs one signature of anyone.
- A comparison says, for each attempt, whether its signatures would meet those
  rules: a junior's can be the right decision and still not be enough.
- Roles come only from the signatures in the graph. Nothing is inferred from
  GitHub, and nothing is ever written.

Its own requirements are in [`idd/`](idd); `tl -C idd context` explains them.
