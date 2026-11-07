"""不需要本机真实日志的界面回归：夹具容器驱动加载、曲线、参数、世界系与截图。

真实交付物的界面验收由 WINDTRACE_TEST_FLIGHTS 提供的历史 .wtr 另行覆盖。
"""
import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets

from ui.main_window import MainWindow
from wtr_builder import hop_flight, write


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return write(tmp_path_factory.mktemp("wtr") / "fixture.wtr", **hop_flight())


def new_window(tmp_path, sample):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / "fixture.ini"), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.load([sample])
    window.timer.stop()
    window.show()
    app.processEvents()
    return app, window


def test_load_curves_parameters_and_scene(tmp_path, sample):
    app, window = new_window(tmp_path, sample)
    try:
        assert window.flight is not None and not window.welcome.isVisible()
        assert window.play.isEnabled() and window.slider.isEnabled()
        assert window.view.plotter is not None, window.view.error
        assert len(window.view.actors) >= 7  # 机体 + 六舵面
        assert window.view.rotor_actor is not None
        assert window.field_combo.count() > 0
        window.curve_button.setChecked(True)
        app.processEvents()
        assert window.curve_drawer.isVisible() and window.plot.listDataItems()
        assert window.parameters.table.rowCount() == len(window.flight.parameters)
        window.show_parameters()
        app.processEvents()
        assert window.parameters_dialog.isVisible()
        window.parameters_dialog.close()
    finally:
        window.close()
        app.processEvents()


def test_world_frame_and_screenshot(tmp_path, sample):
    app, window = new_window(tmp_path, sample)
    try:
        view = window.view
        assert view.world_frame == "NED"
        window.world_frame_combo.setCurrentIndex(window.world_frame_combo.findData("ENU"))
        app.processEvents()
        assert view.world_frame == "ENU" and "ENU" in view.badge.text()
        png = tmp_path / "view.png"
        assert window.screenshot(png)
        assert png.is_file() and png.stat().st_size > 1000
    finally:
        window.close()
        app.processEvents()


def test_playback_advances_with_wall_clock(tmp_path, sample, monkeypatch):
    app, window = new_window(tmp_path, sample)
    try:
        clock = [500.0]
        monkeypatch.setattr("ui.main_window.time.monotonic", lambda: clock[0])
        window.toggle_play()
        for step in range(121):
            clock[0] = 500 + step / 60
            window.advance()
        duration = window.flight.manifest["duration_s"]
        assert window._current_time == pytest.approx(2.0, abs=0.01)
        assert window.slider.value() == round(2.0 / duration * 10000)
        window.toggle_play()
        assert np.isfinite(window.view.rotations).all()
    finally:
        window.close()
        app.processEvents()
