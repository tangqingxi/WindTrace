"""世界系 NED/ENU 切换与机体系显示。"""
import os

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets

from ui.main_window import MainWindow


def source():
    value = os.environ.get('WINDTRACE_TEST_FLIGHTS', '')
    if not value:
        pytest.skip('集成运行提供真实.wtr')
    return value.split(os.pathsep)[0]


def new_window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / 'frames.ini'), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.load([source()])
    window.timer.stop()
    window.slider.setValue(round(20 / window.flight.manifest['duration_s'] * 10000))
    app.processEvents()
    return app, window


def test_switch_ned_enu_and_body_frame(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        assert view.world_frame == 'NED'
        assert np.asarray(view.actors[0].user_matrix)[2, 3] < -5
        assert view.badge.text().count('NED') == 1
        window.world_frame_combo.setCurrentIndex(window.world_frame_combo.findData('ENU'))
        app.processEvents()
        assert view.world_frame == 'ENU'
        assert np.asarray(view.actors[0].user_matrix)[2, 3] > 5
        assert 'ENU' in view.badge.text()
        assert view.plotter.camera.up[2] > 0.9
        window.world_frame_combo.setCurrentIndex(window.world_frame_combo.findData('NED'))
        app.processEvents()
        assert view.world_frame == 'NED'
        assert np.asarray(view.actors[0].user_matrix)[2, 3] < -5
        assert view.plotter.camera.up[2] < -0.9
        assert len(view.body_frame_actors) == 3
        assert not view.body_frame_actors[0].GetVisibility()
        window.body_frame_switch.setChecked(True)
        app.processEvents()
        assert all(actor.GetVisibility() for actor in view.body_frame_actors)
        first = np.asarray(view.body_frame_actors[0].user_matrix).copy()
        window.slider.setValue(round(22 / window.flight.manifest['duration_s'] * 10000))
        app.processEvents()
        second = np.asarray(view.body_frame_actors[0].user_matrix)
        assert np.linalg.norm(first[:3, 3] - second[:3, 3]) > 1e-4
        # 真实b系：b1=+y_FRD，b2=-x_FRD，b3=+z_FRD。
        R = view.display_rotation @ view.rotations[view._att_index]
        np.testing.assert_allclose(np.asarray(view.body_frame_actors[0].user_matrix)[:3, 0], R[:, 1], atol=1e-9)
        np.testing.assert_allclose(np.asarray(view.body_frame_actors[1].user_matrix)[:3, 1], -R[:, 0], atol=1e-9)
        np.testing.assert_allclose(np.asarray(view.body_frame_actors[2].user_matrix)[:3, 2], R[:, 2], atol=1e-9)
    finally:
        window.close(); app.processEvents()


def test_camera_preset_in_enu_keeps_scene_consistent(tmp_path):
    app, window = new_window(tmp_path)
    try:
        window.world_frame_combo.setCurrentIndex(window.world_frame_combo.findData('ENU'))
        window.select_camera_preset('analysis')
        app.processEvents()
        camera = window.view.plotter.camera
        assert camera.position[2] > 0
        assert camera.up[2] > 0.9
        assert np.asarray(window.view.actors[0].user_matrix)[2, 3] > 5
    finally:
        window.close(); app.processEvents()




