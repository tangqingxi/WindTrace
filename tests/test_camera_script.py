"""运镜脚本：解析、校验与按任务时间的确定性求值。"""
from pathlib import Path

import numpy as np
import pytest

from ui.camera import (CameraScriptError, Pose, builtin_script, evaluate,
                       load_camera_script, parse_camera_script)

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "cameras"


def pose(position=(0.0, 0.0, -5.0), radius=0.4):
    return Pose(position=np.array(position, dtype=float),
                forward=np.array([1.0, 0.0, 0.0]),
                right=np.array([0.0, -1.0, 0.0]),
                fov_deg=30.0, model_radius_m=radius,
                model_center_m=np.array([0.0, 0.0, -0.33]),
                path_center=np.array([0.0, 0.0, -5.0]), path_radius_m=5.5)


def test_examples_parse():
    for path in sorted(ASSETS.glob("*.json")):
        script = load_camera_script(path)
        assert script.shots and script.name
        assert script.shots[0].start_s == 0.0


def test_fixed_shot_is_constant():
    script = parse_camera_script({
        "schema": "windtrace.camera.v1", "name": "fixed",
        "shots": [{"start_s": 0, "end_s": 10, "mode": "fixed",
                   "position_m": [3, 4, 5], "target_m": [0, 0, 1]}],
    })
    first = evaluate(script, 0.0, pose())
    second = evaluate(script, 9.9, pose())
    np.testing.assert_allclose(first.position, [3, 4, 5])
    np.testing.assert_allclose(second.position, [3, 4, 5])
    np.testing.assert_allclose(first.focal_point, [0, 0, 1])


def test_orbit_radius_and_vehicle_center():
    script = parse_camera_script({
        "schema": "windtrace.camera.v1", "name": "orbit",
        "shots": [{"start_s": 0, "end_s": 20, "mode": "orbit", "radius_m": 4.0,
                   "azimuth_deg": 0, "elevation_deg": 0}],
    })
    state = evaluate(script, 10.0, pose())
    center = np.array([0.0, 0.0, -5.0]) + np.array([0.0, 0.0, -0.33])
    assert np.linalg.norm(state.position - center) == pytest.approx(4.0, abs=1e-9)
    np.testing.assert_allclose(state.focal_point, center)


def test_chase_offsets_in_heading_frame():
    script = parse_camera_script({
        "schema": "windtrace.camera.v1", "name": "chase",
        "shots": [{"start_s": 0, "end_s": 10, "mode": "chase", "offset_m": [-4.0, 0.0, 1.5]}],
    })
    state = evaluate(script, 1.0, pose())
    center = np.array([0.0, 0.0, -5.0]) + np.array([0.0, 0.0, -0.33])
    np.testing.assert_allclose(state.position, center + np.array([-4.0, 0.0, -1.5]))


def test_transition_blends_from_previous_end():
    script = parse_camera_script({
        "schema": "windtrace.camera.v1", "name": "cut",
        "shots": [
            {"start_s": 0, "end_s": 10, "mode": "fixed", "position_m": [10, 0, 0], "target_m": [0, 0, 0]},
            {"start_s": 10, "end_s": 20, "mode": "fixed", "position_m": [0, 10, 0], "target_m": [0, 0, 0],
             "transition_s": 2.0},
        ],
    })
    start = evaluate(script, 10.0, pose())
    middle = evaluate(script, 11.0, pose())
    end = evaluate(script, 12.0, pose())
    np.testing.assert_allclose(start.position, [10, 0, 0], atol=1e-9)
    np.testing.assert_allclose(end.position, [0, 10, 0], atol=1e-9)
    assert 0.0 < middle.position[0] < 10.0
    assert 0.0 < middle.position[1] < 10.0


def test_hold_last_shot_after_end_and_clamp_times():
    script = parse_camera_script({
        "schema": "windtrace.camera.v1", "name": "short",
        "shots": [{"start_s": 2, "end_s": 4, "mode": "fixed", "position_m": [0, 0, 3], "target_m": [0, 0, 0]}],
    })
    np.testing.assert_allclose(evaluate(script, 0.0, pose()).position, [0, 0, 3])
    np.testing.assert_allclose(evaluate(script, 99.0, pose()).position, [0, 0, 3])


def test_builtin_overview_frames_whole_path():
    overview = evaluate(builtin_script("overview", 55), 5.0, pose())
    distance = np.linalg.norm(overview.position - overview.focal_point)
    assert distance > 5.5
    closeup = evaluate(builtin_script("closeup", 55), 5.0, pose())
    assert np.linalg.norm(closeup.position - closeup.focal_point) < distance


@pytest.mark.parametrize("document,message", [
    ({"schema": "wrong", "shots": []}, "schema"),
    ({"schema": "windtrace.camera.v1", "shots": []}, "至少"),
    ({"schema": "windtrace.camera.v1", "shots": [{"start_s": 0, "end_s": 1, "mode": "fly"}]}, "mode"),
    ({"schema": "windtrace.camera.v1", "shots": [{"start_s": 0, "end_s": 1, "mode": "fixed", "position_m": [0, 0, 1]}]}, "target_m"),
    ({"schema": "windtrace.camera.v1", "shots": [{"start_s": 0, "end_s": 1, "mode": "fixed", "position_m": [0, 0, 1], "target_m": [0, 0, 0], "zoom": 2}]}, "未知字段"),
    ({"schema": "windtrace.camera.v1", "shots": [
        {"start_s": 0, "end_s": 5, "mode": "fixed", "position_m": [0, 0, 1], "target_m": [0, 0, 0]},
        {"start_s": 4, "end_s": 9, "mode": "fixed", "position_m": [0, 0, 1], "target_m": [0, 0, 0]}]}, "重叠"),
    ({"schema": "windtrace.camera.v1", "shots": [
        {"start_s": 0, "end_s": 1, "mode": "fixed", "position_m": [0, 0, 1], "target_m": [0, 0, 0], "transition_s": 2}]}, "transition_s"),
])
def test_invalid_documents_raise_readable_errors(document, message):
    with pytest.raises(CameraScriptError) as error:
        parse_camera_script(document)
    assert message in str(error.value)
