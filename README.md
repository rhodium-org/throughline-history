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

`derive`, `summarise` and `compare` read only what they are given: no git, no
network, no process. The caller fetches the commits; `tl-history` does that from
a local checkout, a page does it from GitHub.

## What it reads, and what it does not

- Items are read through throughline's own reader, so every format the graph was
  ever written in reads as one history. A migration rewrites a signature; it does
  not make one.
- A signature is dated by the time it recorded (format 4) or, before that, by the
  commit that carried it, and each event says which.
- Roles come only from the signatures in the graph. Nothing is inferred from
  GitHub, and nothing is ever written.

Its own requirements are in [`idd/`](idd); `tl -C idd context` explains them.
