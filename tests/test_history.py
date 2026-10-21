import csv

from brainsolpi.history import COLS, REC_COLS, History, Recorder


def row(x):
    return (x, x + 1, 0.5, 900.0, 12.345, None, 1.2345)


def test_span_returns_the_last_rows_in_order():
    h = History(size=10)
    for t in range(100, 105):
        h.push(t + 0.3, row(t))
    out = h.span(900)
    assert out["cols"] == list(COLS)
    assert out["t0"] == 100
    assert out["dt"] == 1
    assert [r[0] for r in out["rows"]] == [100, 101, 102, 103, 104]
    assert out["rows"][0] == [100, 101, 0.5, 900.0, 12.35, None, 1.234]
    assert h.span(2)["t0"] == 103


def test_ring_wraps_and_keeps_the_newest():
    h = History(size=10)
    for t in range(0, 25):
        h.push(t, row(t))
    out = h.span(900)
    assert len(out["rows"]) == 10
    assert out["t0"] == 15
    assert out["rows"][-1][0] == 24


def test_gaps_stay_empty_so_rows_line_up_with_time():
    h = History(size=100)
    h.push(10, row(10))
    h.push(13, row(13))
    out = h.span(900)
    assert out["t0"] == 10
    assert [r[0] for r in out["rows"]] == [10, None, None, 13]


def test_same_second_overwrites():
    h = History(size=10)
    h.push(5.1, row(1))
    h.push(5.9, row(2))
    assert [r[0] for r in h.span(10)["rows"]] == [2]


def test_empty_history():
    assert History().span(900) == {"t0": None, "dt": 1, "cols": list(COLS), "rows": []}
    assert History().span(900, now=1234.5)["t0"] == 1234


def test_recorder_writes_a_csv(tmp_path):
    rec = Recorder(tmp_path)
    path = rec.start(100.0)
    values = ("auto", "locked") + (1.25,) * 17 + (None, float("nan"))
    assert len(values) == len(REC_COLS) - 1
    for i in range(5):
        assert rec.add(100.0 + i * 0.02, values)
    rec.flush()
    rec.stop()
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(REC_COLS)
    assert len(rows) == 6
    assert rows[1][:4] == ["0", "auto", "locked", "1.25"]
    assert rows[-1][-2:] == ["", ""]
    assert not rec.add(200.0, values)


def test_recorder_stops_at_its_length_cap(tmp_path):
    rec = Recorder(tmp_path)
    rec.start(0.0)
    assert not rec.add(Recorder.MAX_SECONDS + 1, ("auto",))
    assert not rec.on
