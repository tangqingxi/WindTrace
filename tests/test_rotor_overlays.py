"""转子显示自转、分析叠加与 HUD 的集成检查。"""
import math
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
    settings = QtCore.QSettings(str(tmp_path / 'view.ini'), QtCore.QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.load([source()])
    window.timer.stop()
    return app, window


def local_rotor_angle(view):
    pose = np.asarray(view.actors[0].user_matrix)[:3, :3]
    rotor = np.asarray(view.rotor_actor.user_matrix)[:3, :3]
    local = pose.T @ rotor
    return math.atan2(local[1, 0], local[0, 0])


def test_rotor_spins_and_can_stop(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        assert view.rotor_actor is not None
        view.set_time(0.0)
        view.set_time(0.1)
        angle = local_rotor_angle(view)
        expected = math.fmod(2 * math.pi * 2.0 * 0.1, 2 * math.pi)
        error = (angle - expected + math.pi) % (2 * math.pi) - math.pi
        assert abs(error) < 0.05
        view.set_rotor_spinning(False)
        view.set_time(0.1)
        stopped = local_rotor_angle(view)
        stopped_error = (stopped + math.pi) % (2 * math.pi) - math.pi
        assert abs(stopped_error) < 0.02
    finally:
        window.close()
        app.processEvents()


def test_analysis_overlays_and_hud(tmp_path):
    app, window = new_window(tmp_path)
    try:
        view = window.view
        assert view.ground_line_actor is not None and view.ground_ring_actor is not None
        assert view.reference_marker_actor is not None and view.reference_line_actor is not None
        window.slider.setValue(round(20 / window.flight.manifest['duration_s'] * 10000))
        app.processEvents()
        text = view.badge.text()
        assert 'Δx' in text and 'Δy' in text and 'Δz' in text and 'z ' in text
        view.set_ground_projection(False)
        assert not view.ground_line_actor.GetVisibility()
        view.set_ground_projection(True)
        assert view.ground_line_actor.GetVisibility()
    finally:
        window.close()
        app.processEvents()
