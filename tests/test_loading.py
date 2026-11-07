"""覆盖空启动、后台读入、失败恢复与“欢迎页列出最近日志、双击打开”。"""
import json
import os
import threading
import time
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
import ui.main_window as module
from ui.main_window import MainWindow


def pump(app, predicate):
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def new_window(tmp_path, name='settings.ini'):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / name), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(no_3d=True, settings=settings)
    window.show()
    app.processEvents()
    return app, window


def sources():
    value = os.environ.get('WINDTRACE_TEST_FLIGHTS', '')
    if not value:
        pytest.skip('集成运行提供真实.wtr')
    return value.split(os.pathsep)


def test_empty_window_explains_and_blocks_playback(tmp_path):
    app, window = new_window(tmp_path)
    try:
        assert window.welcome.isVisible() and '打开' in window.welcome_title.text()
        assert not window.play.isEnabled() and not window.slider.isEnabled()
        assert not window.timer.isActive()
        assert window.recent_list.count() == 0 and window.recent_empty.isVisible()
        window.toggle_play(); window.curve_button.toggle(); app.processEvents()
        assert not window.playing and not window.curve_drawer.isVisible()
        assert window.open_button.isEnabled() and window.welcome_open.isVisible()
        assert window.welcome.width() == 420 and window.welcome.height() < 320
        assert window.welcome_open.height() >= 44
        assert window.camera_combo.currentData() == 'follow'
    finally:
        window.close(); app.processEvents()


def test_background_load_keeps_event_loop_responsive(tmp_path, monkeypatch):
    path = sources()[0]; app, window = new_window(tmp_path); gate = threading.Event(); original = module.read_flight

    def slow_read(path):
        assert gate.wait(5)
        return original(path)

    monkeypatch.setattr(module, 'read_flight', slow_read)
    try:
        window.load_async([path]); assert window.loading and window.load_progress.isVisible()
        assert not window.play.isEnabled() and not window.open_button.isEnabled()
        heartbeat = []
        QtCore.QTimer.singleShot(20, lambda: heartbeat.append(True))
        pump(app, lambda: bool(heartbeat)); assert window.loading
        gate.set(); pump(app, lambda: not window.loading)
        assert window.flight is not None and not window.welcome.isVisible()
        assert window.play.isEnabled() and window.last_error == ''
        assert window.settings.value('recent_file') == str(window.flight.path.resolve())
        entries = json.loads(window.settings.value('recent_files'))
        assert entries and entries[0]['path'] == str(window.flight.path.resolve())
    finally:
        gate.set(); window.close(); app.processEvents()


def test_failed_open_keeps_previous_flight_and_allows_retry(tmp_path):
    path = sources()[0]; app, window = new_window(tmp_path); bad = tmp_path / 'broken.wtr'; bad.write_bytes(b'broken')
    try:
        window.load_async([path]); pump(app, lambda: not window.loading); previous = window.flight
        window.load_async([bad]); pump(app, lambda: not window.loading)
        assert window.flight is previous and window.last_error
        assert window.welcome_title.text() == '日志未能打开' and window.open_button.isEnabled()
        assert window.settings.value('recent_file') == str(previous.path.resolve())
        window.load_async([path]); pump(app, lambda: not window.loading)
        assert not window.last_error and not window.welcome.isVisible()
    finally:
        window.close(); app.processEvents()


def test_startup_lists_recent_without_autoload(tmp_path):
    paths = sources(); app, window = new_window(tmp_path)
    try:
        window.load_async([paths[0]]); pump(app, lambda: not window.loading)
        window.load_async([paths[1]]); pump(app, lambda: not window.loading)
        window.close(); app.processEvents()
        settings = QtCore.QSettings(str(tmp_path / 'settings.ini'), QtCore.QSettings.Format.IniFormat)
        restored = MainWindow(no_3d=True, settings=settings)
        restored.show(); app.processEvents()
        try:
            assert restored.flight is None and not restored.loading
            assert restored.welcome.isVisible()
            assert restored.recent_list.count() == 2
            first = restored.recent_list.item(0)
            assert first.data(QtCore.Qt.ItemDataRole.UserRole) == str(Path(paths[1]).resolve())
            restored.recent_list.itemActivated.emit(first)
            pump(app, lambda: not restored.loading)
            assert restored.flight is not None
            assert str(restored.flight.path.resolve()) == str(Path(paths[1]).resolve())
            assert not restored.welcome.isVisible()
        finally:
            restored.close(); app.processEvents()
    finally:
        app.processEvents()


def test_missing_recent_path_is_reported_without_switching(tmp_path):
    app, window = new_window(tmp_path, name='missing.ini')
    try:
        missing = str(tmp_path / 'gone.wtr')
        window.settings.setValue('recent_files', json.dumps([{'path': missing, 'method': 'WLS', 'seed': 503}]))
        window.settings.sync()
        window._refresh_recent_list()
        assert window.recent_list.count() == 1
        window.recent_list.itemActivated.emit(window.recent_list.item(0))
        app.processEvents()
        assert window.flight is None
        assert '已移动或删除' in window.welcome_hint.text()
        assert window.welcome.isVisible()
    finally:
        window.close(); app.processEvents()


def test_second_open_replaces_current_flight(tmp_path):
    paths = sources(); app, window = new_window(tmp_path, name='single.ini')
    try:
        window.load_async([paths[0]]); pump(app, lambda: not window.loading)
        window.load_async([paths[1]]); pump(app, lambda: not window.loading)
        assert len(window.flights) == 1
        assert str(window.flight.path.resolve()) == str(Path(paths[1]).resolve())
        assert window.run_combo.count() == 1
    finally:
        window.close(); app.processEvents()


def test_recent_requires_double_click(tmp_path):
    paths = sources(); app, window = new_window(tmp_path, name='click.ini')
    try:
        window.settings.setValue('recent_files', json.dumps([{'path': str(Path(paths[0]).resolve()), 'method': 'PCA_PREDICTIVE', 'seed': 501, 'duration_s': 55.0}]))
        window.settings.sync(); window._refresh_recent_list()
        item = window.recent_list.item(0); rect = window.recent_list.visualItemRect(item)
        QTest.mouseClick(window.recent_list.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center())
        app.processEvents()
        assert window.flight is None and not window.loading
        QTest.mouseDClick(window.recent_list.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=rect.center())
        pump(app, lambda: not window.loading)
        assert window.flight is not None
    finally:
        window.close(); app.processEvents()


def test_legacy_recent_file_is_migrated(tmp_path):
    path = str(Path(sources()[0]).resolve())
    app, window = new_window(tmp_path, name='legacy.ini')
    try:
        window.settings.setValue('recent_file', path)
        window.settings.remove('recent_files')
        window.settings.sync()
        window._refresh_recent_list()
        assert window.recent_list.count() == 1
        assert window.recent_list.item(0).data(QtCore.Qt.ItemDataRole.UserRole) == path
    finally:
        window.close(); app.processEvents()
