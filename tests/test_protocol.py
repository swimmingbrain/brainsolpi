import pytest

from brainsolpi.drivers.protocol import (
    CommandReader,
    Frame,
    Ident,
    LineReader,
    Notice,
    Pong,
    cmd_move,
    cmd_ping,
    cmd_rate,
    cmd_slew,
    parse_command,
    parse_line,
)


def test_sample_frame():
    f = parse_line("S,65535,0,8184,4000,12,9600,0,0,1500,2500,5")
    assert isinstance(f, Frame)
    assert f.seq == 65535
    assert f.raw == (0, 8184, 4000, 12)
    assert (f.lux10, f.mv, f.ua) == (9600, 0, 0)
    assert (f.pan_us, f.tilt_us, f.flags) == (1500, 2500, 5)
    assert f.line() == "S,65535,0,8184,4000,12,9600,0,0,1500,2500,5"


@pytest.mark.parametrize("line", [
    "S,1,2,3",
    "S,1,0,0,0,0,0,0,0,0,0,0,0",
    "S,70000,0,0,0,0,0,0,0,0,0,0",
    "S,1,9000,0,0,0,0,0,0,0,0,0",
    "S,1,-1,0,0,0,0,0,0,0,0,0",
    "S,1,a,0,0,0,0,0,0,0,0,0",
    "S,1, 2,0,0,0,0,0,0,0,0,0",
    "S,1,1_0,0,0,0,0,0,0,0,0,0",
    "I,other,1.0.0,1",
    "I,brainsol,1.0.0",
    "X,1",
    "",
    "P,",
])
def test_bad_lines_are_ignored(line):
    assert parse_line(line) is None


def test_identity_and_caps():
    i = parse_line("I,brainsol,1.0.0,3")
    assert i == Ident("1.0.0", 3)
    assert i.lux and i.pv
    assert not parse_line("I,brainsol,1.2.0,0").lux


def test_pong_and_notice():
    assert parse_line("P,42") == Pong(42)
    assert parse_line("E,1,bad command") == Notice(1, "bad command")
    assert parse_line("E,2,line too long, dropped") == Notice(2, "line too long, dropped")


def test_commands_are_clamped_and_ascii():
    assert cmd_move(1500.4, 2600) == b"M,1500,2500\n"
    assert cmd_move(100, 1499.6) == b"M,500,1500\n"
    assert cmd_rate(0) == b"R,1\n"
    assert cmd_rate(500) == b"R,100\n"
    assert cmd_slew(30) == b"L,30\n"
    assert cmd_ping(70000) == b"P,4464\n"


def test_reader_joins_chunks_and_strips_cr():
    r = LineReader()
    assert r.feed(b"P,1\r\nS,1,") == ["P,1"]
    assert r.feed(b"2,3,4,5,6,7,8,9,10,11\n") == ["S,1,2,3,4,5,6,7,8,9,10,11"]
    assert r.feed(b"\n\n") == ["", ""]


def test_reader_drops_overlong_lines_and_recovers():
    r = LineReader()
    assert r.feed(b"x" * 97 + b"\nP,2\n") == ["P,2"]
    assert r.feed(b"y" * 300) == []
    assert r.feed(b"y" * 300) == []
    assert r.feed(b"tail\nP,3\n") == ["P,3"]
    assert r.dropped == 2
    assert r.feed(b"z" * 96 + b"\r\n") == ["z" * 96]


def test_reader_drops_non_ascii():
    r = LineReader()
    assert r.feed(b"\xff\xfe\nP,4\n") == ["P,4"]


@pytest.mark.parametrize("line,want", [
    # the cases of the host test of the sketch, firmware/test/bridge_test.cpp
    ("P,12345678901234567890", ("P", "12345678901234567890")),
    ("P,123456789012345678901", ("E", 1, "bad number")),
    ("P,12a", ("E", 1, "bad number")),
    ("p,7", ("P", "7")),
    ("X", ("E", 1, "unknown command")),
    ("MM,1,2", ("E", 1, "unknown command")),
    (",", ("E", 1, "unknown command")),
    ("M,1500", ("E", 1, "wrong field count")),
    ("M,1500,1500,1", ("E", 1, "wrong field count")),
    ("M,1,2,3,4,5,6", ("E", 1, "wrong field count")),
    ("D,1", ("E", 1, "wrong field count")),
    ("M,15a0,1500", ("E", 1, "bad number")),
    ("M,,1500", ("E", 1, "bad number")),
    ("M,1500, 1500", ("E", 1, "bad number")),
    ("M,9999999999,1500", ("E", 1, "bad number")),
    ("M,-,1500", ("E", 1, "bad number")),
    ("R,", ("E", 1, "bad number")),
    ("P," + "1" * 94, ("E", 1, "bad number")),
    # a half line left from an earlier session glued to the next question
    ("M,15?", ("E", 1, "wrong field count")),
    ("m,-20,999999999", ("M", -20, 999999999)),
    ("l,500", ("L", 500)),
])
def test_board_side_parser_follows_the_sketch(line, want):
    assert parse_command(line) == want


def test_board_line_buffer_follows_the_sketch():
    r = CommandReader()
    assert r.feed(b"\n\r\n\n") == []
    assert r.feed(b"M,1500\r,1500\n") == [("M,1500,1500", None)]
    assert r.feed(b"A" * 300 + b"\n?\n") == [("", "E,2,line too long"), ("?", None)]
    assert r.feed(b"P," + b"1" * 94 + b"\n") == [("P," + "1" * 94, None)]
    assert r.feed(b"P," + b"1" * 95 + b"\n") == [("", "E,2,line too long")]
    assert r.feed(b"\xff\x00\x13M,1500,1500\n") == [("", "E,1,bad character")]
    assert r.feed(b"M,15") == []
    assert r.feed(b"00,1500\n") == [("M,1500,1500", None)]


def test_board_side_commands():
    assert parse_command("M,1500,900") == ("M", 1500, 900)
    assert parse_command("R,50") == ("R", 50)
    # out of range values reach the board, it clamps them
    assert parse_command("R,0") == ("R", 0)
    assert parse_command("L,201") == ("L", 201)
    assert parse_command("?") == ("?",)
    assert parse_command("D") == ("D",)
    assert parse_command("P,7") == ("P", "7")
    assert parse_command("M,1") == ("E", 1, "wrong field count")
    assert parse_command("hello") == ("E", 1, "unknown command")
