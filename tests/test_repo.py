import yaml

from throughline_history import Commit
from throughline_history.repo import derive_repo
from helpers import commit, item, TOML

SHAPE = TOML.replace('name = "fixture"', 'name = "shape"') + '\n[[sources]]\nnamespace = "library"\npath = "../library"\n'
LIB = TOML.replace('name = "fixture"', 'name = "library"')
REG = lambda prefix, typ: yaml.safe_dump({"prefix": prefix, "title": prefix, "type": typ})


def steps_without_lineage():
    return [
        (commit(1, message="Shape"), {"idd/shape/throughline.toml": SHAPE,
                                      "idd/shape/decisions/.register.yml": REG("DEC", "decision"),
                                      "idd/shape/decisions/DEC-0001.yml": item("DEC-0001", type="decision", links=())}),
        (commit(2, message="Library"), {"idd/library/throughline.toml": "# shape DEC-0001: the requirements register\n" + LIB,
                                        "idd/library/requirements/.register.yml": REG("REQ", "requirement"),
                                        "idd/library/requirements/REQ-0001.yml": item("REQ-0001", links=(("REQ-0002", "relates"),)),
                                        "idd/library/requirements/REQ-0002.yml": item("REQ-0002", links=())}),
        (commit(3, message="Stride"), {"idd/library/throughline.toml": LIB + '\n[[sources]]\nnamespace = "stride"\nurl = "https://github.com/o/stride"\nref = "v1"\n',
                                       "idd/library/requirements/REQ-0002.yml": item("REQ-0002", links=(("stride:THR-0001", "mitigates"), ("asvs:V1", "implements")))}),
    ]


def test_no_lineage_is_shown_where_none_is_recorded():
    """REQ-0016: a repository's graphs are followed together, and a graph that
    records no [shaped_by] has no lineage, whatever composes it, comes before it
    or is said in its comments (TEST-0017)."""
    out = derive_repo(steps_without_lineage()).to_json()
    graphs = {g["root"]: g for g in out["graphs"]}
    assert set(graphs) == {"idd/shape", "idd/library"}
    assert graphs["idd/library"]["shapedBy"] is None and graphs["idd/shape"]["shapedBy"] is None
    assert out["lineage"] == []
    # The shape graph composes the library: that is a source, said as one, not lineage.
    assert graphs["idd/shape"]["sources"] == [{"namespace": "library", "kind": "graph", "path": "../library", "graph": "idd/library"}]
    assert graphs["idd/library"]["registers"] == [{"dir": "requirements", "prefix": "REQ", "title": "REQ", "type": "requirement"}]
    kinds = [(e["kind"], e.get("graph")) for e in out["events"] if e["uid"] == ""]
    assert ("graph-created", "idd/shape") in kinds and ("graph-created", "idd/library") in kinds
    assert ("source-declared", "idd/library") in kinds and not any(k == "shaped" for k, _ in kinds)


def test_links_are_classed_by_where_they_reach():
    """REQ-0017: a link is local, to a sibling graph or another repository its
    configuration declares, or under a namespace it does not declare; each
    commit counts the links by where they reach and items by node type (TEST-0018)."""
    out = derive_repo(steps_without_lineage()).to_json()
    linked = {e["target"]: e["scope"] for e in out["events"] if e["kind"] == "linked"}
    assert linked == {"stride:THR-0001": "external", "asvs:V1": "undeclared"}
    last = out["commits"][-1]["graphs"]["idd/library"]
    assert last["linksTo"] == {"external:stride": 1, "local": 1, "undeclared:asvs": 1}
    assert last["byType"] == {"requirement": 2}


def test_recorded_lineage_is_shown_exactly():
    """REQ-0016: once a graph records [shaped_by], it is shown as recorded: the
    shape graph it names and the decision behind each register, as an event and
    as a lineage edge (TEST-0017)."""
    s = steps_without_lineage() + [(commit(4, message="Lineage"), {"idd/library/throughline.toml": LIB + '\n[shaped_by]\ngraph = "../shape"\nregisters = { REQ = "DEC-0001" }\n'})]
    out = derive_repo(s).to_json()
    assert out["lineage"] == [{"from": "idd/shape", "to": "idd/library", "registers": {"REQ": "DEC-0001"}, "known": True}]
    shaped = [e for e in out["events"] if e["kind"] == "shaped"]
    assert len(shaped) == 1 and shaped[0]["by"] == "idd/shape" and shaped[0]["commit"]["sha"] == commit(4).sha
    # The stride source dropped in the same rewrite is said so.
    assert any(e["kind"] == "source-dropped" and e.get("namespace") == "stride" for e in out["events"])


def test_a_graph_removed_and_its_items_belong_to_the_deepest_graph():
    """REQ-0016: a graph whose configuration goes is removed; an item belongs to
    the deepest graph holding it (TEST-0017)."""
    s = [(commit(1), {"throughline.toml": LIB, "requirements/REQ-0001.yml": item("REQ-0001", links=()),
                      "skills/x/idd/throughline.toml": SHAPE.replace("../library", "../../.."), "skills/x/idd/decisions/DEC-0001.yml": item("DEC-0001", type="decision", links=())}),
         (commit(2), {"skills/x/idd/throughline.toml": None})]
    out = derive_repo(s).to_json()
    graphs = {g["root"]: g for g in out["graphs"]}
    assert graphs["skills/x/idd"]["removed"]["sha"] == commit(2).sha
    created = {e["uid"]: e["graph"] for e in out["events"] if e["kind"] == "created"}
    assert created == {"REQ-0001": "", "DEC-0001": "skills/x/idd"}


def test_a_link_into_a_sibling_graph_keeps_its_own_graph():
    """REQ-0017: a link from one graph into a sibling graph is the linking graph's
    event, and names the graph it reaches separately (TEST-0018)."""
    s = steps_without_lineage() + [(commit(4), {
        "idd/library/throughline.toml": LIB + '\n[[sources]]\nnamespace = "shape"\npath = "../shape"\n',
        "idd/library/requirements/REQ-0001.yml": item("REQ-0001", links=(("shape:DEC-0001", "derives_from"),))})]
    out = derive_repo(s).to_json()
    e = next(e for e in out["events"] if e["kind"] == "linked" and e["target"] == "shape:DEC-0001")
    assert (e["graph"], e["scope"], e["into"]) == ("idd/library", "graph", "idd/shape")
