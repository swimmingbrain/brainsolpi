from __future__ import annotations

import io
import logging
import re
import time
from pathlib import Path

from .jsonio import BackgroundWriter, read_json, write_atomic

log = logging.getLogger(__name__)

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _csv_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


class ExperimentStore:
    # one json file per result in the data folder, recent ones are also kept in memory

    def __init__(self, folder: Path | None, writer: BackgroundWriter | None = None):
        self.folder = folder
        self.writer = writer
        self._cache: dict[str, dict] = {}
        self._index: dict[str, dict] = {}
        if folder is not None:
            self._load_index()

    def _load_index(self) -> None:
        try:
            files = sorted(self.folder.glob("*.json"))
        except OSError:
            return
        for path in files:
            data = read_json(path)
            if data and ID_RE.match(str(data.get("id", ""))):
                self._index[data["id"]] = self._entry(data)

    @staticmethod
    def _entry(data: dict) -> dict:
        return {"id": data["id"], "kind": data.get("kind"), "ts": data.get("ts"), "summary": data.get("summary")}

    def new_id(self, kind: str, wall: float | None = None) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(wall if wall is not None else time.time()))
        base = f"{kind}-{stamp}"
        eid = base
        n = 2
        while eid in self._index or eid in self._cache:
            eid = f"{base}-{n}"
            n += 1
        return eid

    def save(self, result: dict) -> None:
        eid = result["id"]
        self._cache[eid] = result
        self._index[eid] = self._entry(result)
        if self.folder is None:
            return
        path = self.folder / f"{eid}.json"
        if self.writer is not None:
            self.writer.write(path, result)
        else:
            try:
                write_atomic(path, result)
            except OSError as e:
                log.warning("cannot save experiment %s: %s", eid, e)

    def list(self) -> list[dict]:
        return sorted(self._index.values(), key=lambda e: e.get("ts") or 0, reverse=True)

    def get(self, eid: str) -> dict | None:
        if not ID_RE.match(eid):
            return None
        if eid in self._cache:
            return self._cache[eid]
        if self.folder is None or eid not in self._index:
            return None
        return read_json(self.folder / f"{eid}.json")

    def csv(self, eid: str) -> str | None:
        data = self.get(eid)
        if data is None:
            return None
        cols, rows = table(data)
        out = io.StringIO()
        out.write(",".join(cols) + "\n")
        for row in rows:
            out.write(",".join(_csv_cell(v) for v in row) + "\n")
        return out.getvalue()


def table(record: dict) -> tuple[list[str], list[list]]:
    # the rows of a result as a flat table, one layout per kind of experiment
    r = record.get("result") or {}
    kind = record.get("kind")
    if kind == "cosine":
        fit = {d: v for d, v in r.get("fit") or []}
        return ["delta", "lux", "fit"], [[d, lux, fit.get(d)] for d, lux in r.get("points") or []]
    if kind == "compare":
        rounds = r.get("rounds") or []
        return ["round", "fixed", "tracked", "gain"], [
            [i + 1, x.get("fixed"), x.get("tracked"), x.get("gain")] for i, x in enumerate(rounds)
        ]
    if kind == "step":
        return ["t", "ex", "ey", "pan", "tilt"], r.get("samples") or []
    return [], []
