"""继承WindTrace源项目的示意GLB网格解析；来源见IMPORT_PROVENANCE.json。"""










from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pyvista as pv

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
COMPONENT_DTYPE = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}
TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


BODY_FIX = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, -1.0, 0.0],
    ]
)


@dataclass(frozen=True)
class VanePart:
    mesh: pv.PolyData
    center: np.ndarray
    axis: np.ndarray
    angle: float


@dataclass(frozen=True)
class GLBParts:
    body: pv.PolyData
    vanes: tuple[VanePart, ...]
    rotor: pv.PolyData | None
    rotor_center: np.ndarray


def _chunks(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 12:
        raise ValueError("GLB is shorter than its header")
    magic, version, length = struct.unpack("<III", data[:12])
    if magic != GLB_MAGIC or version != 2:
        raise ValueError("not a glTF 2.0 binary file")
    if length > len(data):
        raise ValueError("truncated GLB")
    offset = 12
    doc: dict | None = None
    binary = b""
    while offset + 8 <= length:
        chunk_len, chunk_type = struct.unpack("<II", data[offset : offset + 8])
        offset += 8
        payload = data[offset : offset + chunk_len]
        offset += chunk_len
        if chunk_type == CHUNK_JSON:
            doc = json.loads(payload.decode("utf-8"))
        elif chunk_type == CHUNK_BIN:
            binary = payload
    if doc is None:
        raise ValueError("GLB has no JSON chunk")
    return doc, binary


def _accessor(doc: dict, binary: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(COMPONENT_DTYPE[acc["componentType"]])
    components = TYPE_COMPONENTS[acc["type"]]
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(view.get("byteStride", dtype.itemsize * components))
    count = int(acc["count"])
    if stride == dtype.itemsize * components:
        arr = np.frombuffer(binary, dtype=dtype, count=count * components, offset=start)
        arr = arr.reshape(count, components)
    else:
        arr = np.ndarray(
            shape=(count, components),
            dtype=dtype,
            buffer=binary,
            offset=start,
            strides=(stride, dtype.itemsize),
        )
    return np.array(arr, copy=True)


def _read_full_mesh(path: str | Path) -> pv.PolyData:
    data = Path(path).read_bytes()
    doc, binary = _chunks(data)
    points: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    base = 0
    for mesh in doc.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                continue
            attrs = primitive.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            pos = _accessor(doc, binary, attrs["POSITION"]).astype(np.float64)
            n = len(pos)
            if "indices" in primitive:
                idx = _accessor(doc, binary, primitive["indices"]).ravel().astype(np.int64)
            else:
                idx = np.arange(n, dtype=np.int64)
            if len(idx) < 3:
                continue
            tri = idx[: len(idx) // 3 * 3].reshape(-1, 3) + base
            f = np.empty((len(tri), 4), dtype=np.int64)
            f[:, 0] = 3
            f[:, 1:] = tri
            points.append(pos)
            faces.append(f.ravel())
            if "NORMAL" in attrs:
                normals.append(_accessor(doc, binary, attrs["NORMAL"]).astype(np.float64))
            base += n
    if not points:
        raise ValueError("GLB contains no triangle primitives")
    pts = np.vstack(points) @ BODY_FIX.T
    mesh = pv.PolyData(pts, np.concatenate(faces))
    if len(normals) == len(points):
        nr = np.vstack(normals) @ BODY_FIX.T
        mesh.point_data["Normals"] = nr
    mesh.compute_normals(
        cell_normals=False,
        point_normals=True,
        auto_orient_normals=True,
        inplace=True,
    )
    mesh.set_active_scalars(None)
    return mesh


@lru_cache(maxsize=2)
def load_glb_parts(path: str | Path) -> GLBParts:
    """继承WindTrace源项目的示意GLB网格解析；来源见IMPORT_PROVENANCE.json。"""
    mesh = _read_full_mesh(path).clean(tolerance=1e-6)
    conn = mesh.connectivity("all")
    cell_regions = np.asarray(conn.cell_data["RegionId"])
    point_regions = np.asarray(conn.point_data["RegionId"])
    candidates: list[VanePart] = []
    vane_ids: set[int] = set()
    leg_points: list[np.ndarray] = []
    for rid in np.unique(cell_regions):
        mask = point_regions == rid
        pts = conn.points[mask]
        if len(pts) < 50 or len(pts) > 90:
            continue
        center = pts.mean(axis=0)
        radial = float(np.hypot(center[0], center[1]))

        if not (0.035 <= radial <= 0.09 and 0.135 <= center[2] <= 0.185):
            continue
        vane_ids.add(int(rid))
        axis = np.array([center[0], center[1], 0.0], dtype=float)
        axis /= max(float(np.linalg.norm(axis)), 1e-9)
        vane_mesh = conn.extract_cells(np.where(cell_regions == rid)[0]).extract_surface(algorithm="dataset_surface")
        vane_mesh.points = vane_mesh.points - center
        vane_mesh.set_active_scalars(None)
        angle = math.atan2(float(center[1]), float(center[0]))
        candidates.append(VanePart(vane_mesh, center, axis, angle))
    if len(candidates) != 6:
        raise ValueError(f"expected 6 control surfaces, found {len(candidates)}")
    for rid in np.unique(cell_regions):
        pts = conn.points[point_regions == rid]
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        span = hi - lo
        if (len(pts) > 500 and hi[2] > 0.22 and span[0] > 0.20) or (
            50 <= len(pts) <= 75 and span[2] > 0.15 and hi[2] > 0.18
        ):
            leg_points.append(pts)
    rotor_ids: set[int] = set()
    rotor_mesh = None
    rotor_center = np.array([0.0, 0.0, 0.033], dtype=float)
    for rid in np.unique(cell_regions):
        pts = conn.points[point_regions == rid]
        if not (300 < len(pts) < 700):
            continue
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        span = hi - lo
        if span[2] < 0.03 and span[0] > 0.15 and span[1] > 0.15:
            rotor_ids.add(int(rid))
            rotor_mesh = conn.extract_cells(np.where(cell_regions == rid)[0]).extract_surface(
                algorithm="dataset_surface"
            )
            rotor_mesh.points = rotor_mesh.points - rotor_center
            rotor_mesh.compute_normals(
                cell_normals=False,
                point_normals=True,
                auto_orient_normals=True,
                inplace=True,
            )
            rotor_mesh.set_active_scalars(None)
    if len(rotor_ids) != 1:
        rotor_mesh = None


    start = 0.0
    candidates.sort(key=lambda part: (part.angle - start) % (2.0 * math.pi))
    body_cells = np.where(~np.isin(cell_regions, list(vane_ids | rotor_ids)))[0]
    body = conn.extract_cells(body_cells).extract_surface(algorithm="dataset_surface")
    body_conn = body.connectivity("all")
    region = np.asarray(body_conn.point_data["RegionId"])
    part = np.zeros(body.n_points, dtype=np.uint8)
    for rid in np.unique(region):
        pts = body.points[region == rid]
        if len(pts) == 0:
            continue
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        span = hi - lo
        if len(pts) > 3000 and np.hypot(lo[0], lo[1]) > 0.1:
            code = 1
        elif 300 < len(pts) < 700 and span[1] < 0.03 and span[0] > 0.15:
            code = 2
        elif 50 <= len(pts) <= 75 and lo[1] < -0.20 and hi[1] > 0.02:
            code = 3
        else:
            code = 0
        part[region == rid] = code
    if leg_points:
        leg_pts = np.vstack(leg_points)
        d2 = ((body.points[:, None, :] - leg_pts[None, :, :]) ** 2).sum(axis=2)
        part[d2.min(axis=1) < 1e-10] = 3
    body.point_data["part"] = part
    body.compute_normals(
        cell_normals=False,
        point_normals=True,
        auto_orient_normals=True,
        inplace=True,
    )
    body.set_active_scalars(None)
    return GLBParts(body=body, vanes=tuple(candidates), rotor=rotor_mesh, rotor_center=rotor_center)


@lru_cache(maxsize=2)
def load_glb_mesh(path: str | Path) -> pv.PolyData:
    """继承WindTrace源项目的示意GLB网格解析；来源见IMPORT_PROVENANCE.json。"""
    return _read_full_mesh(path)


def model_path() -> Path:
    return Path(__file__).with_name("assets") / "SHC09.glb"
