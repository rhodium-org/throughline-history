# Working on throughline-history (for AI agents)

This repository is self-hosting: its requirements are a throughline graph in
[`idd/`](idd). Before changing anything, run `tl -C idd context` and read it.

- Every change cites the item it serves (`REQ-NNNN`, `NFR-NNNN`) in its commit.
- A behaviour change changes its requirement and its test in the same commit; each
  test's docstring names its `TEST-NNNN`.
- `derive.py` and `compare.py` must never read git, the network, a process or the
  clock: they run in a browser tab (REQ-0009). Only `git.py` reads git.
- Change the graph only through `tl`; never hand-edit an item's structure.
- Before committing: `pytest -q` and `tl -C idd check`.
