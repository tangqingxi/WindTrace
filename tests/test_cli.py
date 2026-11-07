"""命令行入口：--smoke 成功时输出摘要，非法容器以非零码明确报错（窗口版EXE同样适用）。"""
import json
import sys

import pytest

import app
from wtr_builder import hop_flight, write


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["app.py", *argv])
    return app.main()


def test_smoke_prints_summary(tmp_path, monkeypatch, capsys):
    path = write(tmp_path / "flight.wtr", **hop_flight())
    assert run(monkeypatch, "--smoke", str(path)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary[0]["run_id"] == "fixture_s901"
    assert summary[0]["duration_s"] == pytest.approx(10.99875)
    assert summary[0]["topics"] == 11


def test_smoke_writes_report(tmp_path, monkeypatch, capsys):
    path = write(tmp_path / "flight.wtr", **hop_flight())
    report = tmp_path / "report.json"
    assert run(monkeypatch, "--smoke", str(path), "--report", str(report)) == 0
    capsys.readouterr()
    assert json.loads(report.read_text(encoding="utf-8"))[0]["run_id"] == "fixture_s901"


def test_smoke_rejects_invalid_container(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "broken.wtr"
    bad.write_bytes(b"not a zip container")
    assert run(monkeypatch, "--smoke", str(bad)) == 2
    assert "WindTrace:" in capsys.readouterr().err


def test_smoke_rejects_missing_file(tmp_path, monkeypatch, capsys):
    assert run(monkeypatch, "--smoke", str(tmp_path / "absent.wtr")) == 2
    assert "WindTrace:" in capsys.readouterr().err
