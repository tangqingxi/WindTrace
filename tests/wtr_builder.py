"""测试专用 WTR v1 生成器。

只服务测试：直接按 ``windtrace.flight.v1`` 契约写出容器，不读取 MATLAB 日志，
也不依赖历史工程的导出器或 MATLAB 环境。用户运行 WindTrace 不需要本模块。

生成器同时负责把随包的 SHC09 示意 GLB 转成容器内的 FRD 网格，这样测试夹具
的几何与真实交付物同源；转换只在这里做一次，Viewer 运行时不再做坐标变换。
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from scipy.io import savemat

SCHEMA = "windtrace.flight.v1"
PARAMETERS_SCHEMA = "windtrace.parameters.v1"
GEOMETRY_SCHEMA = "windtrace.geometry.v1"
ROOT = Path(__file__).resolve().parents[1]
# SHC09 原生系到 FRD 的一次性变换：向量右乘 C，旋转为 R_FRD_NED=R_SHC_NED@C.T。
C = np.array([[0., 1., 0.], [-1., 0., 0.], [0., 0., 1.]])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def add_topic(topics, specs, name, times, fields, domain, frame):
    """写入一个topic；fields为{字段: (数组, 单位, 来源[, 是否允许NaN])}。"""
    times = np.asarray(times, float).reshape(-1)
    topics[name] = {"time_s": times, "timestamp": np.round(times * 1e6).astype(np.uint64)}
    specs[name] = {"domain": domain, "frame": frame, "fields": {}}
    for field, value in fields.items():
        array = np.asarray(value[0]).reshape(times.size, -1)
        topics[name][field] = array
        specs[name]["fields"][field] = {
            "unit": value[1],
            "source": value[2],
            "width": int(array.shape[1]),
            "allow_nan": bool(value[3]) if len(value) > 3 else False,
        }
    return topics


@lru_cache(maxsize=1)
def vehicle_geometry() -> dict:
    """按 assets/geometry_source.json 与随包 GLB 生成与真实交付物同源的 FRD 几何。"""
    from ui.glb_model import load_glb_parts, model_path

    source_path = ROOT / "assets" / "geometry_source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    vehicle = source["vehicle"]
    vertices = np.asarray(vehicle["vane_vertices"]).T
    hinges = np.column_stack([
        vehicle["l1_m"] * vertices[:, 0],
        vehicle["l1_m"] * vertices[:, 1],
        np.full(6, vehicle["l2_m"]),
    ]) @ C.T
    axes = np.column_stack([-vertices[:, 1], vertices[:, 0], np.zeros(6)]) @ C.T

    parts = load_glb_parts(model_path())

    def encode(mesh):
        return {
            "points": (np.asarray(mesh.points) @ C.T).tolist(),
            "faces": np.asarray(mesh.faces).tolist(),
            "part": np.asarray(mesh.point_data.get("part", [])).tolist(),
        }

    body = parts.body.copy()
    if parts.rotor is not None:
        rotor = parts.rotor.copy()
        rotor.points = rotor.points + parts.rotor_center
        rotor.point_data["part"] = np.full(rotor.n_points, 2, dtype=np.uint8)
        body = body.merge(rotor, merge_points=False)
    geometry = {
        "schema": GEOMETRY_SCHEMA,
        "frame": "FRD",
        "source_sha256": digest(source_path.read_bytes()),
        "assumed": source["assumed"],
        "vehicle": {
            "body_box_m": vehicle["body_box_m"],
            "duct_outer_m": vehicle["duct_outer_m"],
            "duct_inner_m": vehicle["duct_inner_m"],
            "vane_limit_rad": vehicle["vane_limit_rad"],
            "hinges_m": hinges.tolist(),
            "axes": axes.tolist(),
            "vane_ids": [str(i) for i in range(1, 7)],
        },
        "meshes": {"body": encode(body), "vanes": []},
        "visual_note": "测试夹具几何来自随包示意网格；舵面轴为显示假设，不代表气动效能或实测铰链。",
    }
    # 按原生 V1–V6 径向方向一一对应示意舵面，与交付物使用同一配对规则。
    candidates = list(parts.vanes)
    for target in hinges:
        scores = [
            np.dot((vane.center @ C.T)[:2], target[:2])
            / (np.linalg.norm(vane.center[:2]) * np.linalg.norm(target[:2]))
            for vane in candidates
        ]
        vane = candidates.pop(int(np.argmax(scores)))
        geometry["meshes"]["vanes"].append({
            **encode(vane.mesh),
            "center": (vane.center @ C.T).tolist(),
            "axis": (vane.axis @ C.T).tolist(),
        })
    return geometry


def write(path, *, topics, specs, parameters, geometry=None, run_id="fixture_s901",
          method="CUSTOM_ALLOCATOR", seed=901, scenario="fixture",
          duration_s=None, execution_status="completed", audit_status="unknown",
          source=None, parameter_arrays=None):
    """写出一个合法的 WTR 容器；已存在则直接抛 FileExistsError，绝不覆盖。"""
    path = Path(path)
    if path.suffix.lower() != ".wtr":
        raise ValueError("测试样本必须是 .wtr 路径")
    geometry = vehicle_geometry() if geometry is None else geometry
    arrays = dict(parameter_arrays or {})
    duration_s = float(duration_s if duration_s is not None else max(
        float(np.asarray(topic["time_s"], float).max()) for topic in topics.values()))
    manifest = {
        "schema": SCHEMA,
        "run_id": run_id,
        "method": method,
        "seed": seed,
        "scenario": scenario,
        "duration_s": duration_s,
        "execution": {"status": execution_status, "expected_duration_s": duration_s},
        "audit": {"original": {"status": audit_status}, "saved_checks": {},
                  "policy": "测试夹具；原驱动记录保留，未知不等于通过"},
        "source": {"log_sha256": digest(path.name.encode("utf-8")), "filename": path.name,
                   "sidecar_sha256": {}, "engine": "test-fixture",
                   "input_signature": "fixture", "input_signature_scope": "test_only",
                   "records": {}},
        "time_origin": "relative mission start; no absolute UTC",
        "topics": specs,
        "missing_topics": [],
        "unknown_parameter_fields": [],
    }
    if source:
        manifest["source"].update(source)
    buffer = io.BytesIO()
    savemat(buffer, {"topics": topics, "parameter_arrays": arrays},
            do_compression=True, long_field_names=True)
    members = {
        "parameters.json": json_bytes({"schema": PARAMETERS_SCHEMA, "entries": parameters,
                                       "unknown_fields": []}),
        "flight.mat": buffer.getvalue(),
        "geometry.json": json_bytes(geometry),
    }
    manifest["members"] = {name: {"sha256": digest(payload), "bytes": len(payload)}
                           for name, payload in members.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        import zipfile
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in {"manifest.json": json_bytes(manifest), **members}.items():
                archive.writestr(name, payload)
    return path


def hop_flight(duration_s=11.0, rate_hz=800, pwm_rate_hz=333.0):
    """生成一段悬停爬升的合成飞行：覆盖全部核心topic与两类独立时钟。"""
    times = np.arange(int(round(duration_s * rate_hz))) / rate_hz
    count = times.size
    position = np.column_stack([
        0.1 * np.sin(times),
        0.2 * np.cos(times),
        -10.0 * np.minimum(times / max(duration_s, 1e-9), 1.0),
    ])
    velocity = np.gradient(position, times, axis=0)
    euler = np.column_stack([0.05 * np.sin(times), 0.04 * np.cos(times), 0.3 * times])
    from scipy.spatial.transform import Rotation
    quat = Rotation.from_euler("ZYX", euler[:, ::-1]).as_quat()[:, [3, 0, 1, 2]]
    quat[quat[:, 0] < 0] *= -1
    estimated = position + np.array([0.3, 0.4, 0.0])
    control = np.flatnonzero(np.arange(count) % 2 == 0)
    vane = 0.2 * np.sin(times)
    vanes = np.column_stack([vane * (1 + 0.1 * index) for index in range(6)])
    topics, specs = {}, {}
    for suffix, data in [("", estimated), ("_groundtruth", position)]:
        add_topic(topics, specs, "vehicle_local_position" + suffix, times,
                  {"x": (data[:, 0], "m", "fixture"), "y": (data[:, 1], "m", "fixture"),
                   "z": (data[:, 2], "m", "fixture"),
                   "vx": (velocity[:, 0], "m/s", "fixture"), "vy": (velocity[:, 1], "m/s", "fixture"),
                   "vz": (velocity[:, 2], "m/s", "fixture")},
                  "estimate" if suffix else "truth", "NED")
        add_topic(topics, specs, "vehicle_attitude" + suffix, times,
                  {"q": (quat, "1", "fixture")},
                  "estimate" if suffix else "truth", "FRD_to_NED")
    add_topic(topics, specs, "trajectory_setpoint", times,
              {"position": (position, "m", "fixture"), "velocity": (velocity, "m/s", "fixture"),
               "acceleration": (np.zeros_like(position), "m/s^2", "fixture")}, "reference", "NED")
    add_topic(topics, specs, "vehicle_attitude_reference", times,
              {"q": (quat, "1", "fixture")}, "reference", "FRD_to_NED")
    add_topic(topics, specs, "shc09_vanes", times,
              {"actual": (vanes, "rad", "fixture"), "estimated": (vanes * 0.95, "rad", "fixture")},
              "truth_and_estimate_separate", "1-6")
    add_topic(topics, specs, "vehicle_rates_reference", times,
              {"xyz": (np.full((count, 3), 0.01), "rad/s", "fixture")}, "reference", "reference_FRD")
    # 400Hz 控制更新点与 333Hz 锁存PWM各用自身时钟，不插值对齐。
    add_topic(topics, specs, "shc09_indi", times[control],
              {"v_h": (np.tile([1., 2., 3.], (control.size, 1)), "rad/s^2", "fixture"),
               "v_c": (np.tile([4., 5., 6.], (control.size, 1)), "rad/s^2", "fixture")},
              "controller", "estimated_FRD")
    add_topic(topics, specs, "shc09_allocation", times[control],
              {"lambda": (np.full((control.size, 1), np.nan), "1", "fixture", True),
               "mode": (np.zeros((control.size, 1)), "1", "fixture")}, "allocator", "none")
    pwm_times = np.arange(int(round(duration_s * pwm_rate_hz))) / pwm_rate_hz
    pwm_times = pwm_times[pwm_times <= times[-1]]
    add_topic(topics, specs, "actuator_servos_pwm", pwm_times,
              {"command_rad": (np.zeros((pwm_times.size, 6)), "rad", "fixture")},
              "pwm_latched", "1-6")
    big = np.arange(240, dtype=float).reshape(80, 3)
    parameters = [
        {"path": "controller.indi_output_filter_hz", "value": 15.0, "type": "float",
         "unit": "Hz", "source": "saved.plan.controller", "overridden": True,
         "baseline_value": 8.0, "baseline_source": "saved.spec.parent_controller"},
        {"path": "cfg.unbounded", "value": {"special_float": "+Inf"}, "type": "float",
         "unit": "unknown", "source": "saved.cfg", "overridden": False},
        {"path": "cfg.missing_value", "value": {"special_float": "NaN"}, "type": "float",
         "unit": "unknown", "source": "saved.cfg", "overridden": False},
        {"path": "cfg.large", "value": {"key": "p00000", "shape": [80, 3], "dtype": "float64"},
         "type": "array_ref", "unit": "unknown", "source": "saved.cfg", "overridden": False},
    ]
    return dict(topics=topics, specs=specs, parameters=parameters, duration_s=float(times[-1]),
                parameter_arrays={"p00000": big})
