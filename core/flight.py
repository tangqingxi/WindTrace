"""严格读取自包含.wtr；不解压到磁盘，也不读取外部配置。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
from scipy.io import loadmat
from scipy.spatial.transform import Rotation

SCHEMA = "windtrace.flight.v1"
MEMBERS = {"manifest.json", "parameters.json", "flight.mat", "geometry.json"}


class FlightError(ValueError):
    """容器、字段或时间契约不满足要求。"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


@dataclass
class Flight:
    path: Path
    manifest: dict
    parameters: list[dict]
    geometry: dict
    topics: dict
    parameter_arrays: dict

    @property
    def run_id(self):
        return self.manifest["run_id"]

    def field(self, topic, field):
        return np.asarray(self.topics[topic][field])

    def time(self, topic):
        return self.field(topic, "time_s").reshape(-1)

    def position(self, topic):
        if "position" in self.topics[topic]:
            return self.field(topic,"position").reshape(-1,3)
        return np.column_stack([self.field(topic,key).reshape(-1) for key in ("x","y","z")])

    def parameter_value(self, row):
        value = row["value"]
        if row["type"] == "array_ref":
            return self.parameter_arrays[value["key"]].tolist()
        return value


def validate(manifest, topics, geometry):
    if manifest.get("schema") != SCHEMA:
        raise FlightError("不支持的.wtr schema")
    if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]:
        raise FlightError("缺少run_id")
    if geometry.get("frame") != "FRD" or geometry.get("schema") != "windtrace.geometry.v1":
        raise FlightError("几何坐标必须为FRD")
    required={"vehicle_local_position","vehicle_local_position_groundtruth","vehicle_attitude","vehicle_attitude_groundtruth","trajectory_setpoint","vehicle_attitude_reference","shc09_vanes"}
    if not required.issubset(manifest.get("topics",{})):
        raise FlightError("缺少回放所需的核心topic")
    if len(geometry.get("meshes",{}).get("vanes",[]))!=6:
        raise FlightError("缺少自包含六舵面几何")
    for key in ("execution", "audit", "method", "source"):
        if key not in manifest:
            raise FlightError(f"缺少元数据：{key}")
    for name, spec in manifest["topics"].items():
        if name not in topics:
            raise FlightError(f"缺少topic：{name}")
        topic = topics[name]
        time = np.asarray(topic.get("time_s", [])).reshape(-1)
        stamp = np.asarray(topic.get("timestamp", [])).reshape(-1)
        if not time.size or not np.all(np.isfinite(time)) or np.any(time < 0) or np.any(np.diff(time) <= 0):
            raise FlightError(f"{name}时间必须有限、非负、严格递增")
        if stamp.dtype != np.uint64 or not np.array_equal(stamp, np.round(time*1e6).astype(np.uint64)):
            raise FlightError(f"{name}微秒时间戳不匹配")
        if time[-1] > manifest["duration_s"] + 1e-9:
            raise FlightError(f"{name}时间超出飞行范围")
        for field, desc in spec["fields"].items():
            if field not in topic:
                raise FlightError(f"缺少字段：{name}.{field}")
            arr = np.asarray(topic[field]).reshape(time.size, -1)
            if arr.shape[1] != desc["width"] or arr.dtype.kind not in "biuf":
                raise FlightError(f"{name}.{field}形状／类型不匹配")
            if not desc.get("allow_nan", False) and not np.all(np.isfinite(arr)):
                raise FlightError(f"{name}.{field}存在非有限数据")
            if np.any(np.isinf(arr)):
                raise FlightError(f"{name}.{field}存在无穷值")
            if field == "q":
                if not np.allclose(np.linalg.norm(arr, axis=1), 1, atol=1e-8):
                    raise FlightError(f"{name}四元数未归一化")
        if set(topic) != {"time_s", "timestamp", *spec["fields"]}:
            raise FlightError(f"{name}包含未声明字段")
    if set(topics) != set(manifest["topics"]):
        raise FlightError("包含未声明topic")


def read_flight(path):
    path = Path(path)
    if path.suffix.lower() != ".wtr":
        raise FlightError("只接受单飞行.wtr文件")
    try:
        with zipfile.ZipFile(path) as container:
            names = container.namelist()
            if len(names) != len(MEMBERS) or set(names) != MEMBERS:
                raise FlightError("容器成员缺失、重复或包含未声明路径")
            if any(x.file_size > 512*1024**2 for x in container.infolist()):
                raise FlightError("成员超过512MiB限制")
            data = {name: container.read(name) for name in names}
        manifest = json.loads(data["manifest.json"])
        if set(manifest["members"]) != MEMBERS - {"manifest.json"}:
            raise FlightError("成员清单不完整")
        for name, spec in manifest["members"].items():
            if spec != {"sha256": digest(data[name]), "bytes": len(data[name])}:
                raise FlightError(f"成员哈希或长度不匹配：{name}")
        values = loadmat(io.BytesIO(data["flight.mat"]), simplify_cells=True)
        topics = values.get("topics", {})
        geometry = json.loads(data["geometry.json"])
        validate(manifest, topics, geometry)
        parameters = json.loads(data["parameters.json"])
        if parameters.get("schema") != "windtrace.parameters.v1":
            raise FlightError("参数schema不匹配")
        rows = parameters["entries"]
        if len({r["path"] for r in rows}) != len(rows):
            raise FlightError("参数路径重复")
        arrays = values.get("parameter_arrays", {})
        for row in rows:
            if row["type"] == "array_ref" and row["value"]["key"] not in arrays:
                raise FlightError("参数数组引用缺失")
        return Flight(path, manifest, rows, geometry, topics, arrays)
    except FlightError:
        raise
    except Exception as problem:
        raise FlightError(f"无法读取{path.name}：{problem}") from problem


def quaternion_euler(q):
    q = np.asarray(q).reshape(-1, 4)
    return Rotation.from_quat(q[:, [1, 2, 3, 0]]).as_euler("ZYX")[:, ::-1]
