"""内置运镜预设：镜头数量、FOV 与关键时间点可求值。"""
import numpy as np
import pytest

from ui.camera import (Pose, analysis_script, evaluate, load_camera_script, parse_camera_script,
                       showcase_script, vane_closeup_script)


def pose():
    return Pose(position=np.array([0.0, 0.0, -5.0]), forward=np.array([1.0, 0.0, 0.0]),
                right=np.array([0.0, -1.0, 0.0]), fov_deg=30.0, model_radius_m=0.4,
                model_center_m=np.array([0.0, 0.0, -0.33]),
                path_center=np.array([0.0, 0.0, -5.0]), path_radius_m=5.5)


def test_showcase_has_camera_acts():
    script = showcase_script(55.0)
    assert len(script.shots) == 5
    assert script.shots[0].end_s == 12.0
    assert script.shots[1].mode == 'chase'
    assert script.shots[2].mode == 'fixed'
    assert script.shots[-1].end_s == 55.0
    for t in (0, 6, 12, 15, 20, 27, 32, 40, 54):
        state = evaluate(script, t, pose())
        assert np.all(np.isfinite(state.position)) and np.all(np.isfinite(state.focal_point))
        assert 15.0 <= state.fov_deg <= 100.0


def test_analysis_is_static_during_main_window():
    script = analysis_script(55.0)
    first = evaluate(script, 20.0, pose())
    second = evaluate(script, 26.0, pose())
    np.testing.assert_allclose(first.position, second.position, atol=1e-9)
    np.testing.assert_allclose(first.focal_point, second.focal_point, atol=1e-9)


def test_short_flight_clips_presets():
    script = showcase_script(20.0)
    assert all(shot.end_s <= 20.0 for shot in script.shots)
    assert script.shots[-1].end_s == 20.0


def test_fov_is_parsed_and_returned():
    script = parse_camera_script({
        "schema": "windtrace.camera.v1", "name": "fov",
        "shots": [{"start_s": 0, "end_s": 10, "mode": "fixed", "position_m": [3, 4, 5],
                   "target_m": [0, 0, 1], "fov_deg": 50}],
    })
    state = evaluate(script, 1.0, pose())
    assert state.fov_deg == pytest.approx(50.0)


def test_closeup_preset_exists():
    script = vane_closeup_script(55.0)
    assert len(script.shots) == 1 and script.shots[0].mode == 'closeup'
    state = evaluate(script, 20.0, pose())
    assert np.linalg.norm(state.position - state.focal_point) < 5.0
