import json
import math

import pytest

from brainsolpi.config import PARAMS, Settings
from brainsolpi.jsonio import dumps, read_json, write_atomic
from brainsolpi.state import StateStore


def test_dumps_turns_nan_and_infinity_into_null():
    text = dumps({"a": float("nan"), "b": [1.5, float("inf"), {"c": -float("inf")}], "d": None})
    assert json.loads(text) == {"a": None, "b": [1.5, None, {"c": None}], "d": None}
    assert "NaN" not in text and "Infinity" not in text


def test_write_atomic_replaces_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "sub" / "x.json"
    write_atomic(path, {"v": 1})
    write_atomic(path, {"v": 2, "bad": math.nan})
    assert read_json(path) == {"v": 2, "bad": None}
    assert [p.name for p in path.parent.iterdir()] == ["x.json"]


def test_read_json_moves_a_broken_file_aside(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{ not json", encoding="utf-8")
    assert read_json(path) is None
    assert (tmp_path / "s.json.bad").exists()


def test_defaults_match_the_shared_contract():
    s = Settings()
    want = {
        "kp": 90, "vmax": 60, "amax": 240, "dead_in": 0.025, "dead_out": 0.05, "tau": 0.12,
        "min_light": 0.04, "zenith_band": 6, "ref_pan": 0, "ref_tilt": 90, "rate": 20,
    }
    assert {p.key: s.param(p.key) for p in PARAMS} == want
    assert s.pan_limits == (-88, 88)
    assert s.tilt_limits == (4, 176)
    assert s.park == (0, 90)
    assert s.problems == []


def test_out_of_range_values_fall_back_to_defaults():
    s = Settings(data={
        "params": {"kp": 5000, "tau": "fast", "rate": 25, "vmax": True},
        "limits": {"pan": [50, 55], "tilt": [0, 180]},
        "site": {"lat": 120},
    })
    assert s.param("kp") == 90
    assert s.param("tau") == 0.12
    assert s.param("rate") == 25
    assert s.param("vmax") == 60
    assert s.pan_limits == (-88, 88)
    assert s.tilt_limits == (0, 180)
    assert s.site["lat"] == 48.21
    assert len(s.problems) == 5


def test_set_value_checks_ranges_and_relations():
    s = Settings()
    assert s.set_value("kp", 120) == 120
    with pytest.raises(ValueError):
        s.set_value("kp", 9)
    with pytest.raises(ValueError):
        s.set_value("dead_in", 0.06)
    with pytest.raises(ValueError):
        s.set_value("nope", 1)
    with pytest.raises(ValueError):
        s.set_value("rate", float("nan"))
    assert s.set_value("rate", 12.4) == 12
    # ref_pan follows the limits, not the static range
    s.set_value("pan_max", 40)
    with pytest.raises(ValueError):
        s.set_value("ref_pan", 60)
    assert s.cfg()["params"]["ref_pan"]["max"] == 40
    assert s.dirty


def test_settings_round_trip_through_the_file(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings.load(path)
    assert path.exists()
    s.set_value("amax", 300)
    s.set_site(47.5, 9.7, 200)
    s.save()
    again = Settings.load(path)
    assert again.param("amax") == 300
    assert again.site == {"lat": 47.5, "lon": 9.7, "heading": 200}


def test_state_survives_garbage(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"pan": "x", "tilt": 500, "mode": "dance", "sim": {"el": -40}}), encoding="utf-8")
    st = StateStore.load(path)
    assert st.pan == 0.0
    assert st.tilt == 180.0
    assert st.mode == "auto"
    assert st.sim["el"] == 0.0


def test_state_saves_only_when_changed(tmp_path):
    path = tmp_path / "state.json"
    st = StateStore.load(path)
    assert st.save(force=True)
    assert not st.save()
    st.pan = 12.345
    assert st.changed
    assert st.save()
    assert StateStore.load(path).pan == 12.35


def test_background_writer_keeps_the_newest_version(tmp_path):
    from brainsolpi.jsonio import BackgroundWriter

    w = BackgroundWriter()
    path = tmp_path / "a.json"
    for i in range(50):
        w.write(path, {"i": i})
    assert w.flush()
    assert read_json(path) == {"i": 49}
    s = Settings(tmp_path / "s.json")
    s.writer = w
    s.set_value("kp", 100)
    s.save()
    w.close()
    assert read_json(tmp_path / "s.json")["params"]["kp"] == 100
