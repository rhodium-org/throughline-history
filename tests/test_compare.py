from throughline_history import compare
from helpers import TOML, item

ADA = {"by": "Ada", "id": "github:ada", "fingerprint": "sha256:a"}
BOB = {"by": "Bob", "id": "github:bob", "fingerprint": "sha256:b", "role": "senior"}


def files(**items):
    return {"idd/throughline.toml": TOML, **{f"idd/requirements/{u}.yml": t for u, t in items.items()}}


def test_each_attempt_is_set_beside_what_was_kept():
    """REQ-0010: per item, each attempt's decision and whether it agrees with the
    final version; per attempt, how many it decided and how many agreed. Items
    already settled at the start are left out (TEST-0010)."""
    base = files(**{"REQ-0001": item("REQ-0001"), "REQ-0002": item("REQ-0002"), "REQ-0003": item("REQ-0003"),
                    "REQ-0004": item("REQ-0004", status="ratified", signatures=[ADA])})
    junior = files(**{"REQ-0001": item("REQ-0001", status="ratified", signatures=[ADA]),
                      "REQ-0002": item("REQ-0002", status="ratified", signatures=[ADA]),
                      "REQ-0003": item("REQ-0003", status="rejected", attrs={"invalidated_reason": "out of scope"}),
                      "REQ-0004": item("REQ-0004", status="ratified", signatures=[ADA])})
    senior = files(**{"REQ-0001": item("REQ-0001", status="ratified", signatures=[BOB]),
                      "REQ-0002": item("REQ-0002"),
                      "REQ-0003": item("REQ-0003", status="rejected"),
                      "REQ-0004": item("REQ-0004", status="ratified", signatures=[ADA])})
    final = files(**{"REQ-0001": item("REQ-0001", status="ratified", signatures=[BOB]),
                     "REQ-0002": item("REQ-0002", status="rejected"),
                     "REQ-0003": item("REQ-0003", status="rejected"),
                     "REQ-0004": item("REQ-0004", status="ratified", signatures=[ADA])})
    out = compare(base, {"junior": junior, "senior": senior}, final, root="idd")
    assert [r["uid"] for r in out["items"]] == ["REQ-0001", "REQ-0002", "REQ-0003"]
    rows = {r["uid"]: r for r in out["items"]}
    assert rows["REQ-0003"]["attempts"]["junior"] == {"status": "rejected", "decision": "rejected",
                                                      "reason": "out of scope", "agrees": True}
    assert rows["REQ-0001"]["attempts"]["senior"]["roles"] == ["senior"]
    assert rows["REQ-0002"]["attempts"]["junior"]["agrees"] is False
    assert rows["REQ-0002"]["attempts"]["senior"]["decision"] == "undecided"
    totals = {t["name"]: t for t in out["attempts"]}
    assert (totals["junior"]["decided"], totals["junior"]["agreed"]) == (3, 2)
    assert (totals["senior"]["decided"], totals["senior"]["agreed"]) == (2, 2)


def test_the_invalidated_status_is_the_graphs_own():
    """REQ-0011: rejected is whatever the graph names its invalidated status, read
    from its configuration, never assumed (TEST-0011)."""
    toml = TOML.replace('"rejected"', '"refused"').replace('invalidated = "refused"', 'invalidated = "refused"')
    base = {"throughline.toml": toml, "REQ-0001.yml": item("REQ-0001")}
    tried = {"throughline.toml": toml, "REQ-0001.yml": item("REQ-0001", status="refused")}
    out = compare(base, {"a": tried})
    assert out["invalidated"] == "refused"
    assert out["items"][0]["attempts"]["a"]["decision"] == "rejected"
