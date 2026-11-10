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


def test_sync_dry_run_changes_nothing(tmp_path, capsys):
    a, b, f = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    _main(a, "done", "Read", "--date", "2026-03-02", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)
    file_before = f.read_text(encoding="utf-8")
    _main(b, "add", "Gym", capsys=capsys)
    db_before = _main(b, "export", capsys=capsys)[1]

    code, out, _ = _main(b, "sync", str(f), "--dry-run", capsys=capsys)
    assert code == 0 and "would pull 1 new habit, 1 completion" in out
    assert "file would be updated" in out
    assert f.read_text(encoding="utf-8") == file_before
    assert _main(b, "export", capsys=capsys)[1] == db_before


def test_sync_dry_run_missing_file_is_not_created(tmp_path, capsys):
    a, f = tmp_path / "a.db", tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    code, out, _ = _main(a, "sync", str(f), "--dry-run", capsys=capsys)
    assert code == 0 and "Would create" in out and not f.exists()


def test_sync_reports_setting_conflicts_and_keeps_local(tmp_path, capsys):
    a, b, f = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)
    _main(b, "sync", str(f), capsys=capsys)
    _main(a, "edit", "Read", "--target", "3", "--every", "weekly", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)

    code, out, _ = _main(b, "sync", str(f), capsys=capsys)
    assert code == 0
    assert "Conflict: 'Read' every is daily here but weekly in the file; kept daily." in out
    assert "Conflict: 'Read' target is 1 here but 3 in the file; kept 1." in out
    listing = _main(b, "list", "--json", capsys=capsys)[1]
    assert '"every": "daily"' in listing


def test_sync_no_conflict_when_settings_match(tmp_path, capsys):
    a, f = tmp_path / "a.db", tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)
    _, out, _ = _main(a, "sync", str(f), capsys=capsys)
    assert "Conflict" not in out


def _conflicted(tmp_path, capsys):
    a, b, f = tmp_path / "a.db", tmp_path / "b.db", tmp_path / "sync.json"
    _main(a, "add", "Read", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)
    _main(b, "sync", str(f), capsys=capsys)
    _main(a, "edit", "Read", "--target", "3", "--every", "weekly", capsys=capsys)
    _main(a, "archive", "Read", capsys=capsys)
    _main(a, "sync", str(f), capsys=capsys)
    return a, b, f


def test_sync_prefer_file_applies_file_settings(tmp_path, capsys):
    _, b, f = _conflicted(tmp_path, capsys)
    before = f.read_text(encoding="utf-8")
    code, out, _ = _main(b, "sync", str(f), "--prefer", "file", capsys=capsys)
    assert code == 0
    assert "Conflict: 'Read' every was daily here but weekly in the file; changed to weekly." in out
    assert "target was 1 here but 3 in the file; changed to 3." in out
    assert "archived was False here but True in the file; changed to True." in out
    assert f.read_text(encoding="utf-8") == before
    item = json.loads(_main(b, "export", capsys=capsys)[1])["habits"][0]
    assert (item["every"], item["target"], item["archived"]) == ("weekly", 3, True)
    _, out, _ = _main(b, "sync", str(f), "--prefer", "file", capsys=capsys)
    assert "Conflict" not in out


def test_sync_prefer_local_overwrites_file(tmp_path, capsys):
    _, b, f = _conflicted(tmp_path, capsys)
    _main(b, "sync", str(f), "--prefer", "local", capsys=capsys)
    item = json.loads(f.read_text(encoding="utf-8"))["habits"][0]
    assert (item["every"], item["target"], item["archived"]) == ("daily", 1, False)


def test_sync_prefer_file_dry_run_changes_nothing(tmp_path, capsys):
    _, b, f = _conflicted(tmp_path, capsys)
    code, out, _ = _main(b, "sync", str(f), "--prefer", "file", "--dry-run", capsys=capsys)
    assert code == 0 and "would change to weekly" in out
    item = json.loads(_main(b, "export", capsys=capsys)[1])["habits"][0]
    assert (item["every"], item["target"], item["archived"]) == ("daily", 1, False)


def test_sync_prefer_rejects_other_values(tmp_path, capsys):
    a = tmp_path / "a.db"
    try:
        _main(a, "sync", str(tmp_path / "s.json"), "--prefer", "both", capsys=capsys)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected argparse to reject --prefer both")
