from __future__ import annotations

import json
from datetime import date

from habitlog import cli

TODAY = date(2026, 3, 4)


def _main(db, *argv, capsys):
    capsys.readouterr()
    code = cli.main(["--db", str(db), *argv], today=TODAY)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_sync_creates_missing_file(tmp_path, capsys):
    a = tmp_path / "a.db"
    f = tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    _main(a, "done", "Read", "--date", "2026-03-03", capsys=capsys)
    code, out, _ = _main(a, "sync", str(f), capsys=capsys)
    assert code == 0 and "Created" in out and "1 habit" in out
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["habits"][0]["completions"][0]["date"] == "2026-03-03"
    assert not (tmp_path / "sync.json.tmp").exists()


def test_sync_two_databases_converge(tmp_path, capsys):
    a, b, f = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    _main(a, "done", "Read", "--date", "2026-03-02", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)

    _main(b, "add", "Gym", capsys=capsys)
    _main(b, "done", "Gym", "--date", "2026-03-03", capsys=capsys)
    code, out, _ = _main(b, "sync", str(f), capsys=capsys)
    assert code == 0 and "pulled 1 new habit, 1 completion" in out and "file updated" in out

    code, out, _ = _main(a, "sync", str(f), capsys=capsys)
    assert code == 0 and "pulled 1 new habit" in out
    exp_a = json.loads(_main(a, "export", capsys=capsys)[1])
    exp_b = json.loads(_main(b, "export", capsys=capsys)[1])
    assert exp_a == exp_b
    assert sorted(h["name"] for h in exp_a["habits"]) == ["Gym", "Read"]


def test_sync_is_idempotent(tmp_path, capsys):
    a, f = tmp_path / "a.db", tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)
    before = f.read_text(encoding="utf-8")
    code, out, _ = _main(a, "sync", str(f), capsys=capsys)
    assert code == 0 and "already up to date" in out
    assert f.read_text(encoding="utf-8") == before


def test_sync_invalid_file_is_an_error_and_left_alone(tmp_path, capsys):
    a, f = tmp_path / "a.db", tmp_path / "sync.json"
    f.write_text("not json", encoding="utf-8")
    code, _, err = _main(a, "sync", str(f), capsys=capsys)
    assert code == 1 and "not valid JSON" in err
    assert f.read_text(encoding="utf-8") == "not json"
