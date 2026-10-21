from brainsolpi.store import ExperimentStore


def result(eid, ts):
    return {
        "id": eid,
        "kind": "cosine",
        "ts": ts,
        "summary": {"r2": 0.99},
        "result": {"peak": 900, "amb": 60, "r2": 0.99, "points": [[-5, 900.5], [0, 960.0], [5, None]],
                   "fit": [[-5, 900.0], [0, 960.0], [5, 901.0]]},
    }


def test_store_saves_lists_and_exports(tmp_path):
    s = ExperimentStore(tmp_path)
    eid = s.new_id("cosine", 0)
    s.save(result(eid, 1000))
    s.save(result("cosine-b", 2000))
    assert [e["id"] for e in s.list()] == ["cosine-b", eid]
    assert s.get(eid)["summary"] == {"r2": 0.99}
    assert s.csv(eid) == "delta,lux,fit\n-5,900.5,900\n0,960,960\n5,,901\n"
    # a fresh store finds the files again
    again = ExperimentStore(tmp_path)
    assert {e["id"] for e in again.list()} == {eid, "cosine-b"}
    assert again.get("cosine-b")["kind"] == "cosine"


def test_ids_are_unique_and_safe(tmp_path):
    s = ExperimentStore(tmp_path)
    a = s.new_id("step", 0)
    s.save(result(a, 1))
    b = s.new_id("step", 0)
    assert a != b and b.startswith(a)
    assert s.get("../settings") is None
    assert s.get("NOPE") is None
    assert s.csv("missing") is None


def test_store_without_a_folder_keeps_results_in_memory():
    s = ExperimentStore(None)
    s.save(result("x1", 5))
    assert s.get("x1")["id"] == "x1"
    assert s.list()[0]["id"] == "x1"
