"""运镜脚本：只按任务时间求值，不依赖帧率、回放倍速或当前鼠标视角。

文件格式见 docs/windtrace_camera_v1.md；解析失败抛出 CameraScriptError，
界面保留原相机并显示可读的错误，不静默忽略。脚本只描述相机怎么动，不参与控制或评价。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path

import numpy as np

SCHEMA = "windtrace.camera.v1"
MODES = ("fixed", "track", "orbit", "chase", "overview", "closeup")
EASINGS = ("linear", "smoothstep", "smootherstep")
DIRECTIONS = ("isometric", "front", "side", "top")

COMMON_KEYS = {"start_s", "end_s", "mode", "ease", "transition_s", "fov_deg"}
MODE_KEYS = {
    "fixed": {"position_m", "position_end_m", "target_m", "target_end_m"},
    "track": {"position_m", "position_end_m"},
    "orbit": {"radius_m", "azimuth_deg", "azimuth_end_deg", "elevation_deg", "elevation_end_deg"},
    "chase": {"offset_m", "offset_end_m", "look_ahead_m"},
    "overview": {"pad", "direction"},
    "closeup": {"azimuth_deg", "elevation_deg", "distance_scale"},
}
TOP_KEYS = {"schema", "name", "description", "shots"}


class CameraScriptError(ValueError):
    """运镜文件不满足格式或数值契约。"""


@dataclass(frozen=True)
class Shot:
    index: int
    start_s: float
    end_s: float
    mode: str
    params: dict
    ease: str = "smoothstep"
    transition_s: float = 0.0

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class CameraScript:
    name: str
    shots: tuple
    source: str = ""

    def shot_at(self, t: float) -> tuple[Shot, float]:
        """返回 (镜头, 归一化进度)；空档保持上一镜末帧，越界保持首/末镜。"""
        first = self.shots[0]
        if t <= first.start_s:
            return first, 0.0
        for shot in self.shots:
            if shot.start_s <= t < shot.end_s:
                return shot, (t - shot.start_s) / shot.duration_s
        last = self.shots[-1]
        if t >= last.end_s:
            return last, 1.0
        previous = first
        for shot in self.shots:
            if shot.end_s <= t:
                previous = shot
        return previous, 1.0


@dataclass
class Pose:
    """当前机体位姿与取景所需尺寸，单位 m、弧度由调用方换算。"""

    position: np.ndarray
    forward: np.ndarray
    right: np.ndarray
    fov_deg: float = 30.0
    model_radius_m: float = 0.35
    model_center_m: np.ndarray = field(default_factory=lambda: np.zeros(3))
    path_center: np.ndarray | None = None
    path_radius_m: float = 8.0
    up: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, -1.0]))


@dataclass(frozen=True)
class CameraState:
    position: np.ndarray
    focal_point: np.ndarray
    up: np.ndarray
    fov_deg: float = 30.0


def _unit(value) -> np.ndarray:
    array = np.asarray(value, dtype=float).reshape(3)
    return array / max(float(np.linalg.norm(array)), 1e-9)


def _vec3(value, label: str, shot_index: int) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CameraScriptError(f"第{shot_index + 1}个镜头的{label}必须是三个数")
    try:
        array = np.asarray(value, dtype=float).reshape(3)
    except (TypeError, ValueError) as problem:
        raise CameraScriptError(f"第{shot_index + 1}个镜头的{label}不是数值") from problem
    if not np.all(np.isfinite(array)):
        raise CameraScriptError(f"第{shot_index + 1}个镜头的{label}必须是有限数值")
    return array


def _number(params: dict, key: str, shot_index: int, default: float | None = None) -> float:
    if key not in params:
        if default is None:
            raise CameraScriptError(f"第{shot_index + 1}个镜头缺少{key}")
        return float(default)
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CameraScriptError(f"第{shot_index + 1}个镜头的{key}必须是数字")
    value = float(value)
    if not math.isfinite(value):
        raise CameraScriptError(f"第{shot_index + 1}个镜头的{key}必须是有限数值")
    return value


def _ease(name: str, u: float) -> float:
    u = min(1.0, max(0.0, float(u)))
    if name == "linear":
        return u
    if name == "smootherstep":
        return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)
    return u * u * (3.0 - 2.0 * u)


def _direction(name: str) -> np.ndarray:
    table = {
        # NED：x北、y东、z下；相机在地面之上时 z 为负。
        "isometric": (-1.1, 1.0, -0.78),
        "front": (-1.0, 0.0, -0.32),
        "side": (0.0, 1.0, -0.28),
        "top": (0.0, 0.0, -1.0),
    }
    return _unit(table[name])


def _frame_distance(radius: float, fov_deg: float, scale: float) -> float:
    half = math.radians(max(5.0, min(120.0, fov_deg)) / 2.0)
    return max(float(radius), 1e-3) / max(math.sin(half), 1e-3) * float(scale)


def _lerp(a, b, u: float) -> np.ndarray:
    return np.asarray(a, dtype=float) + (np.asarray(b, dtype=float) - np.asarray(a, dtype=float)) * u


def _hermite(p0, m0, p1, m1, u: float):
    u2 = u * u
    u3 = u2 * u
    h00 = 2.0 * u3 - 3.0 * u2 + 1.0
    h10 = u3 - 2.0 * u2 + u
    h01 = -2.0 * u3 + 3.0 * u2
    h11 = u3 - u2
    return h00 * np.asarray(p0, dtype=float) + h10 * np.asarray(m0, dtype=float) + h01 * np.asarray(p1, dtype=float) + h11 * np.asarray(m1, dtype=float)


def _blend_states(first: CameraState, second: CameraState, u: float) -> CameraState:
    position = _lerp(first.position, second.position, u)
    focal = _lerp(first.focal_point, second.focal_point, u)
    up = _unit(_lerp(first.up, second.up, u))
    fov = float(first.fov_deg) + (float(second.fov_deg) - float(first.fov_deg)) * u
    return CameraState(position=position, focal_point=focal, up=up, fov_deg=fov)


def _hermite_states(first: CameraState, first_velocity: CameraState, second: CameraState, second_velocity: CameraState, duration: float, u: float) -> CameraState:
    """C1 过渡：端点位置与速度同时匹配，避免镜头切换时的顿挫。"""
    m0p = np.asarray(first_velocity.position, dtype=float) * duration
    m1p = np.asarray(second_velocity.position, dtype=float) * duration
    m0f = np.asarray(first_velocity.focal_point, dtype=float) * duration
    m1f = np.asarray(second_velocity.focal_point, dtype=float) * duration
    position = _hermite(first.position, m0p, second.position, m1p, u)
    focal = _hermite(first.focal_point, m0f, second.focal_point, m1f, u)
    up = _unit(_hermite(first.up, np.zeros(3), second.up, np.zeros(3), u))
    fov = float(_hermite(np.array([first.fov_deg]), np.array([0.0]), np.array([second.fov_deg]), np.array([0.0]), u)[0])
    return CameraState(position=position, focal_point=focal, up=up, fov_deg=fov)


def parse_camera_script(data, source: str = "") -> CameraScript:
    if not isinstance(data, dict):
        raise CameraScriptError("运镜文件顶层必须是JSON对象")
    unknown = set(data) - TOP_KEYS
    if unknown:
        raise CameraScriptError("运镜文件包含未知字段：" + "、".join(sorted(unknown)))
    if data.get("schema") != SCHEMA:
        raise CameraScriptError(f"运镜schema必须为{SCHEMA}")
    name = data.get("name", "未命名运镜")
    if not isinstance(name, str) or not name.strip():
        raise CameraScriptError("运镜name必须是非空字符串")
    description = data.get("description", "")
    if not isinstance(description, str):
        raise CameraScriptError("description必须是字符串")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        raise CameraScriptError("运镜至少需要一个镜头")
    parsed: list[Shot] = []
    previous_end = -1.0
    for index, item in enumerate(shots):
        if not isinstance(item, dict):
            raise CameraScriptError(f"第{index + 1}个镜头必须是JSON对象")
        mode = item.get("mode")
        if mode not in MODES:
            raise CameraScriptError(f"第{index + 1}个镜头的mode必须是：" + "、".join(MODES))
        allowed = COMMON_KEYS | MODE_KEYS[mode]
        extra = set(item) - allowed
        if extra:
            raise CameraScriptError(
                f"第{index + 1}个镜头({mode})包含未知字段：" + "、".join(sorted(extra))
                + "；可用字段：" + "、".join(sorted(allowed))
            )
        start = _number(item, "start_s", index)
        end = _number(item, "end_s", index)
        if start < 0:
            raise CameraScriptError(f"第{index + 1}个镜头的start_s不能为负")
        if end <= start:
            raise CameraScriptError(f"第{index + 1}个镜头的end_s必须大于start_s")
        if start < previous_end - 1e-9:
            raise CameraScriptError(f"第{index + 1}个镜头与上一个镜头时间重叠")
        previous_end = end
        ease = item.get("ease", "smoothstep")
        if ease not in EASINGS:
            raise CameraScriptError(f"第{index + 1}个镜头的ease必须是：" + "、".join(EASINGS))
        transition = _number(item, "transition_s", index, 0.0)
        if transition < 0:
            raise CameraScriptError(f"第{index + 1}个镜头的transition_s不能为负")
        if transition > end - start + 1e-9:
            raise CameraScriptError(f"第{index + 1}个镜头的transition_s不能超过镜头时长")
        params: dict = {}
        if "fov_deg" in item:
            fov = _number(item, "fov_deg", index)
            if not 15.0 <= fov <= 100.0:
                raise CameraScriptError(f"第{index + 1}个镜头的fov_deg必须在15到100之间")
            params["fov_deg"] = fov
        if mode in ("fixed", "track"):
            if "position_m" not in item:
                raise CameraScriptError(f"第{index + 1}个{mode}镜头缺少position_m")
            params["position_m"] = _vec3(item["position_m"], "position_m", index)
            params["position_end_m"] = _vec3(item["position_end_m"], "position_end_m", index) if "position_end_m" in item else None
            if mode == "fixed":
                if "target_m" not in item:
                    raise CameraScriptError(f"第{index + 1}个fixed镜头缺少target_m")
                params["target_m"] = _vec3(item["target_m"], "target_m", index)
                params["target_end_m"] = _vec3(item["target_end_m"], "target_end_m", index) if "target_end_m" in item else None
        elif mode == "orbit":
            radius = _number(item, "radius_m", index, 4.5)
            if radius <= 0:
                raise CameraScriptError(f"第{index + 1}个镜头的radius_m必须大于0")
            params["radius_m"] = radius
            params["azimuth_deg"] = _number(item, "azimuth_deg", index, 35.0)
            params["azimuth_end_deg"] = _number(item, "azimuth_end_deg", index, params["azimuth_deg"])
            params["elevation_deg"] = _number(item, "elevation_deg", index, 12.0)
            params["elevation_end_deg"] = _number(item, "elevation_end_deg", index, params["elevation_deg"])
            for key in ("elevation_deg", "elevation_end_deg"):
                if not -80.0 <= params[key] <= 80.0:
                    raise CameraScriptError(f"第{index + 1}个镜头的{key}必须在-80到80之间")
        elif mode == "chase":
            if "offset_m" not in item:
                raise CameraScriptError(f"第{index + 1}个chase镜头缺少offset_m")
            params["offset_m"] = _vec3(item["offset_m"], "offset_m", index)
            params["offset_end_m"] = _vec3(item["offset_end_m"], "offset_end_m", index) if "offset_end_m" in item else None
            params["look_ahead_m"] = _number(item, "look_ahead_m", index, 0.0)
        elif mode == "overview":
            pad = _number(item, "pad", index, 1.05)
            if pad < 1.0:
                raise CameraScriptError(f"第{index + 1}个镜头的pad不能小于1.0")
            params["pad"] = pad
            direction = item.get("direction", "isometric")
            if direction not in DIRECTIONS:
                raise CameraScriptError(f"第{index + 1}个镜头的direction必须是：" + "、".join(DIRECTIONS))
            params["direction"] = direction
        elif mode == "closeup":
            params["azimuth_deg"] = _number(item, "azimuth_deg", index, 35.0)
            params["elevation_deg"] = _number(item, "elevation_deg", index, 18.0)
            params["distance_scale"] = _number(item, "distance_scale", index, 2.2)
            if params["distance_scale"] <= 0:
                raise CameraScriptError(f"第{index + 1}个镜头的distance_scale必须大于0")
        parsed.append(Shot(index=index, start_s=start, end_s=end, mode=mode, params=params,
                           ease=ease, transition_s=transition))
    return CameraScript(name=name.strip(), shots=tuple(parsed), source=source)


def load_camera_script(path) -> CameraScript:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as problem:
        raise CameraScriptError(f"无法读取运镜文件：{problem}") from problem
    try:
        data = json.loads(text)
    except json.JSONDecodeError as problem:
        raise CameraScriptError(f"运镜文件不是合法JSON：第{problem.lineno}行{problem.msg}") from problem
    return parse_camera_script(data, source=str(path.resolve()))


def shot_state(shot: Shot, u: float, pose: Pose) -> CameraState:
    progress = _ease(shot.ease, u)
    up = np.asarray(pose.up, dtype=float)
    position = np.asarray(pose.position, dtype=float)
    center = position + np.asarray(pose.model_center_m, dtype=float)
    forward = _unit(np.asarray(pose.forward, dtype=float))
    right = _unit(np.asarray(pose.right, dtype=float))
    params = shot.params
    fov = float(params.get("fov_deg", pose.fov_deg))
    if shot.mode == "fixed":
        start = np.asarray(params["position_m"], dtype=float)
        end = params["position_end_m"]
        camera = _lerp(start, end if end is not None else start, progress)
        target_start = np.asarray(params["target_m"], dtype=float)
        target_end = params["target_end_m"]
        target = _lerp(target_start, target_end if target_end is not None else target_start, progress)
    elif shot.mode == "track":
        start = np.asarray(params["position_m"], dtype=float)
        end = params["position_end_m"]
        camera = _lerp(start, end if end is not None else start, progress)
        target = center
    elif shot.mode == "orbit":
        azimuth = math.radians(params["azimuth_deg"] + (params["azimuth_end_deg"] - params["azimuth_deg"]) * progress)
        elevation = math.radians(params["elevation_deg"] + (params["elevation_end_deg"] - params["elevation_deg"]) * progress)
        radius = float(params["radius_m"])
        offset = np.array([
            radius * math.cos(elevation) * math.cos(azimuth),
            radius * math.cos(elevation) * math.sin(azimuth),
            -radius * math.sin(elevation),
        ])
        camera = center + offset
        target = center.copy()
    elif shot.mode == "chase":
        start = np.asarray(params["offset_m"], dtype=float)
        end = params["offset_end_m"]
        offset = _lerp(start, end if end is not None else start, progress)
        camera = center + forward * offset[0] + right * offset[1] + up * offset[2]
        target = center + forward * float(params["look_ahead_m"])
    elif shot.mode == "overview":
        overview_center = np.asarray(pose.path_center if pose.path_center is not None else center, dtype=float)
        radius = float(pose.path_radius_m)
        distance = _frame_distance(radius, fov, float(params["pad"]))
        camera = overview_center + _direction(params["direction"]) * distance
        target = overview_center
    else:  # closeup
        distance = _frame_distance(pose.model_radius_m, fov, float(params["distance_scale"]))
        azimuth = math.radians(float(params["azimuth_deg"]))
        elevation = math.radians(float(params["elevation_deg"]))
        direction = np.array([
            math.cos(elevation) * math.cos(azimuth),
            math.cos(elevation) * math.sin(azimuth),
            -math.sin(elevation),
        ])
        camera = center + direction * distance
        target = center.copy()
    return CameraState(position=camera, focal_point=target, up=up / max(float(np.linalg.norm(up)), 1e-9), fov_deg=fov)


def _state_velocity(shot: Shot, u: float, pose: Pose, step_s: float = 0.02) -> CameraState:
    """用任务时间前向／中心差分估计镜头状态速度，供 Hermite 过渡匹配。"""
    du = min(0.25, max(1e-6, step_s / max(shot.duration_s, 1e-6)))
    if u <= du:
        a = shot_state(shot, min(1.0, u + du), pose)
        b = shot_state(shot, u, pose)
        dt = du * shot.duration_s
    else:
        a = shot_state(shot, u, pose)
        b = shot_state(shot, u - du, pose)
        dt = du * shot.duration_s
    return CameraState(position=(a.position - b.position) / dt,
                       focal_point=(a.focal_point - b.focal_point) / dt,
                       up=np.zeros(3), fov_deg=(a.fov_deg - b.fov_deg) / dt)


def evaluate(script: CameraScript, t: float, pose: Pose) -> CameraState:
    shot, u = script.shot_at(float(t))
    state = shot_state(shot, u, pose)
    if shot.transition_s > 0 and shot.index > 0:
        elapsed = float(t) - shot.start_s
        if 0.0 <= elapsed < shot.transition_s:
            previous = shot_state(script.shots[shot.index - 1], 1.0, pose)
            v0 = _state_velocity(script.shots[shot.index - 1], 1.0, pose)
            v1 = _state_velocity(shot, u, pose)
            progress = min(1.0, max(0.0, elapsed / shot.transition_s))
            state = _hermite_states(previous, v0, state, v1, shot.transition_s, progress)
    return state


def _preset(name: str, specs) -> CameraScript:
    shots = []
    for index, (start, end, mode, params, transition) in enumerate(specs):
        shots.append(Shot(index=index, start_s=float(start), end_s=float(end), mode=mode,
                          params=dict(params), ease="smoothstep", transition_s=float(transition)))
    return CameraScript(name=name, shots=tuple(shots), source="builtin")


def _clip_specs(specs, end: float):
    """把预设镜头裁到当前日志时长；短日志自动丢弃不存在的镜头。"""
    clipped = []
    for start, finish, mode, params, transition in specs:
        if start >= end:
            break
        finish = min(float(finish), end)
        if finish <= start:
            continue
        clipped.append((start, finish, mode, params, transition))
    return clipped


def showcase_script(duration_s: float = 55.0) -> CameraScript:
    """发布展示：起飞、偏航、扰动固定机位、恢复与收尾。"""
    end = max(float(duration_s), 1.0)
    specs = [
        (0.0, min(12.0, end), "orbit", {"radius_m": 7.5, "azimuth_deg": 40.0, "azimuth_end_deg": 55.0,
                                        "elevation_deg": 18.0, "elevation_end_deg": 32.0, "fov_deg": 36.0}, 0.0),
        (12.0, min(15.0, end), "chase", {"offset_m": np.array([-4.2, 0.0, 1.0]), "offset_end_m": None,
                                         "look_ahead_m": 0.0, "fov_deg": 34.0}, 1.2),
        (15.0, min(27.0, end), "fixed", {"position_m": np.array([5.0, 4.3, -11.2]), "position_end_m": None,
                                         "target_m": np.array([0.0, 0.0, -9.8]), "target_end_m": None, "fov_deg": 50.0}, 1.6),
        (27.0, min(37.0, end), "orbit", {"radius_m": 7.0, "azimuth_deg": 25.0, "azimuth_end_deg": 55.0,
                                         "elevation_deg": 22.0, "elevation_end_deg": 22.0, "fov_deg": 36.0}, 1.5),
        (37.0, end, "orbit", {"radius_m": 8.5, "azimuth_deg": 55.0, "azimuth_end_deg": 70.0,
                              "elevation_deg": 18.0, "elevation_end_deg": 18.0, "fov_deg": 38.0}, 1.5),
    ]
    return _preset("发布演示", _clip_specs(specs, end))


def analysis_script(duration_s: float = 55.0) -> CameraScript:
    """对比分析：固定机位，切换方法时保持同一时刻与机位。"""
    end = max(float(duration_s), 1.0)
    specs = [
        (0.0, min(12.0, end), "fixed", {"position_m": np.array([-10.0, 10.0, -6.0]), "position_end_m": None,
                                        "target_m": np.array([0.0, 0.0, -5.0]), "target_end_m": None, "fov_deg": 55.0}, 0.0),
        (12.0, end, "fixed", {"position_m": np.array([5.0, 4.3, -11.2]), "position_end_m": None,
                              "target_m": np.array([0.0, 0.0, -9.8]), "target_end_m": None, "fov_deg": 52.0}, 1.2),
    ]
    return _preset("对比分析", _clip_specs(specs, end))


def vane_closeup_script(duration_s: float = 55.0) -> CameraScript:
    """舵面特写：随机体平移，低角度看涵道与六舵面。"""
    end = max(float(duration_s), 1.0)
    specs = [
        (0.0, end, "closeup", {"azimuth_deg": 35.0, "elevation_deg": 8.0, "distance_scale": 1.5, "fov_deg": 32.0}, 0.0),
    ]
    return _preset("舵面特写", _clip_specs(specs, end))


def builtin_script(mode: str, duration_s: float) -> CameraScript:
    """把内置相机模式表示成单镜头脚本，保证与导入运镜共用同一求值路径。"""
    end = max(float(duration_s), 1.0)
    if mode == "chase":
        shot = Shot(0, 0.0, end, "chase", {"offset_m": np.array([-4.5, 0.0, 1.8]), "offset_end_m": None,
                                           "look_ahead_m": 0.0, "fov_deg": 30.0})
    elif mode == "orbit":
        shot = Shot(0, 0.0, end, "orbit", {"radius_m": 4.5, "azimuth_deg": 35.0, "azimuth_end_deg": 35.0,
                                           "elevation_deg": 12.0, "elevation_end_deg": 12.0, "fov_deg": 30.0})
    elif mode == "overview":
        shot = Shot(0, 0.0, end, "overview", {"pad": 1.05, "direction": "isometric", "fov_deg": 30.0})
    elif mode == "closeup":
        shot = Shot(0, 0.0, end, "closeup", {"azimuth_deg": 35.0, "elevation_deg": 18.0,
                                             "distance_scale": 2.2, "fov_deg": 30.0})
    else:
        raise CameraScriptError(f"未知内置相机模式：{mode}")
    return CameraScript(name=mode, shots=(shot,), source="builtin")
