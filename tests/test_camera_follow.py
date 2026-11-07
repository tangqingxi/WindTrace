"""回放中的相机模式：默认跟随、自由视角、手动介入与导入运镜。"""
import os
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtWidgets

from PySide6 import QtCore
from ui.main_window import MainWindow

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "cameras"


def source():
    value = os.environ.get('WINDTRACE_TEST_FLIGHTS', '')
    if not value:
        pytest.skip('集成运行提供真实.wtr')
    return value.split(os.pathsep)[0]


def new_window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / 'camera.ini'), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.load([source()])
    window.timer.stop()
    return app, window


def test_default_is_follow_and_translation_preserves_angle(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        assert view.camera_mode == 'follow' and window.camera_combo.currentData() == 'follow'
        camera = view.plotter.camera
        before = np.asarray(camera.focal_point).copy()
        offset = np.asarray(camera.position) - before
        old_position = view._last_position.copy()
        window.slider.setValue(5000)
        np.testing.assert_allclose(np.asarray(camera.focal_point) - before, view._last_position - old_position, atol=1e-12)
        np.testing.assert_allclose(np.asarray(camera.position) - np.asarray(camera.focal_point), offset, atol=1e-12)
        renderer = view.plotter.renderer
        renderer.SetWorldPoint(*view._last_position, 1)
        renderer.WorldToDisplay()
        assert 0 < renderer.GetDisplayPoint()[2] < 1
    finally:
        window.close()
        app.processEvents()


def test_free_mode_keeps_camera_static(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        index = window.camera_combo.findData('free')
        window.camera_combo.setCurrentIndex(index)
        app.processEvents()
        camera = view.plotter.camera
        fixed = np.asarray(camera.focal_point).copy()
        window.slider.setValue(7000)
        np.testing.assert_allclose(camera.focal_point, fixed, atol=1e-12)
    finally:
        window.close()
        app.processEvents()


def test_manual_interaction_switches_to_free(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        assert window.camera_combo.currentData() == 'follow'
        view.plotter.iren.style.InvokeEvent('StartInteractionEvent')
        app.processEvents()
        assert window.camera_combo.currentData() == 'free'
        assert view.camera_mode == 'free'
    finally:
        window.close()
        app.processEvents()


def test_overview_frames_whole_path(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        index = window.camera_combo.findData('overview')
        window.camera_combo.setCurrentIndex(index)
        app.processEvents()
        camera = view.plotter.camera
        distance = np.linalg.norm(np.asarray(camera.position) - np.asarray(camera.focal_point))
        assert distance > view.path_radius_m
        assert view.path_radius_m > 1.0
    finally:
        window.close()
        app.processEvents()


def test_imported_script_moves_camera_with_mission_time(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        assert window.load_camera_file(ASSETS / 'showcase_55s.json')
        data = window.camera_combo.currentData()
        assert isinstance(data, tuple) and data[0] == 'script'
        window.slider.setValue(0)
        app.processEvents()
        first = np.asarray(view.plotter.camera.position).copy()
        window.slider.setValue(round(20 / window.flight.manifest['duration_s'] * 10000))
        app.processEvents()
        second = np.asarray(view.plotter.camera.position).copy()
        assert np.linalg.norm(second - first) > 0.5
        # 同一时刻重复求值必须一致，脚本不依赖帧率或鼠标。
        window.slider.setValue(round(20 / window.flight.manifest['duration_s'] * 10000))
        app.processEvents()
        np.testing.assert_allclose(view.plotter.camera.position, second, atol=1e-9)
    finally:
        window.close()
        app.processEvents()


def test_invalid_script_keeps_previous_camera(tmp_path):
    app, window = new_window(tmp_path)
    try:
        bad = tmp_path / 'bad.json'
        bad.write_text('{"schema":"windtrace.camera.v1","shots":[]}', encoding='utf-8')
        before = window.camera_combo.currentData()
        assert not window.load_camera_file(bad, announce=False)
        assert window.last_camera_error
        assert window.camera_combo.currentData() == before
    finally:
        window.close()
        app.processEvents()
