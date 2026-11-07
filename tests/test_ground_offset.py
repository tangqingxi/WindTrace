"""示意模型按几何底点贴地：最低点在地面，抬升量只影响显示。"""
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


def test_model_lowest_point_sits_on_ground(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / 'ground.ini'), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.load([source()])
    window.timer.stop()
    try:
        view = window.view
        assert view.plotter is not None, view.error
        # 交付几何的腿底相对原点约0.2352 m；抬升值随几何计算，不写死。
        assert view.ground_lift_m == pytest.approx(0.2352, abs=0.02)
        points = np.asarray(view.actors[0].mapper.dataset.points)
        assert points[:, 2].max() == pytest.approx(0.0, abs=1e-6)
        assert view.model_center_m[2] == pytest.approx(-0.327, abs=0.03)
        window.slider.setValue(0)
        app.processEvents()
        R = view.rotations[view._att_index]
        pos = view.position[view._pose_index]
        world = points @ R.T + pos
        assert world[:, 2].max() == pytest.approx(0.0, abs=0.05)
        assert '+0.235' in window.ground_hint.text()
        assert '仅显示' in window.ground_hint.text()
    finally:
        window.close()
        app.processEvents()


def test_lift_is_constant_while_flying(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / 'ground.ini'), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.load([source()])
    window.timer.stop()
    try:
        lift = window.view.ground_lift_m
        window.slider.setValue(4000)
        app.processEvents()
        assert window.view.ground_lift_m == pytest.approx(lift, abs=1e-12)
    finally:
        window.close()
        app.processEvents()

