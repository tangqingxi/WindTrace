"""按 windtrace.flight.v1 契约验证读取端：时钟、数据域、参数来源、几何与拒绝规则。

样本由 tests/wtr_builder.py 现场生成，不经过 MATLAB 转换器，也不依赖历史工程。
"""
import io
import json
import zipfile

import numpy as np
import pytest
from scipy.io import loadmat, savemat

from core.flight import FlightError, digest, quaternion_euler, read_flight
from wtr_builder import hop_flight, json_bytes, write


@pytest.fixture(scope="module")
def sample():
    return hop_flight()


@pytest.fixture
def flight(tmp_path, sample):
    path = write(tmp_path / "flight.wtr", **sample)
    return read_flight(path)


def rewrite(flight, tmp_path, mutate):
    with zipfile.ZipFile(flight.path) as archive:
        data = {name: archive.read(name) for name in archive.namelist()}
    mutate(data)
    path = tmp_path / "bad.wtr"
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in data.items():
            archive.writestr(name, value)
    return path


def test_native_clocks_and_domains(flight, sample):
    assert flight.manifest["method"] == "CUSTOM_ALLOCATOR"
    # 333Hz 锁存PWM保留自身时钟，400Hz控制更新点从800Hz状态记录中抽取，都不插值。
    pwm_time = flight.time("actuator_servos_pwm")
    np.testing.assert_array_equal(pwm_time, sample["topics"]["actuator_servos_pwm"]["time_s"])
    control_time = flight.time("shc09_indi")
    np.testing.assert_array_equal(control_time, sample["topics"]["shc09_indi"]["time_s"])
    assert control_time.size == 4400 and pwm_time.size == 3663
    assert pwm_time[-1] <= flight.manifest["duration_s"] + 1e-9
    assert np.isnan(flight.field("shc09_allocation", "lambda")).all()
    assert flight.manifest["topics"]["shc09_indi"]["domain"] == "controller"
    assert flight.manifest["topics"]["trajectory_setpoint"]["frame"] == "NED"
    assert "sensor_accel" not in flight.topics


def test_position_attitude_are_not_rewritten(flight, sample):
    truth = flight.position("vehicle_local_position_groundtruth")
    estimate = flight.position("vehicle_local_position")
    np.testing.assert_allclose(estimate - truth, np.tile([0.3, 0.4, 0.0], (len(truth), 1)), atol=1e-12)
    np.testing.assert_array_equal(truth, np.column_stack([
        sample["topics"]["vehicle_local_position_groundtruth"][key] for key in ("x", "y", "z")]))
    assert truth[0, 2] == pytest.approx(0.0, abs=1e-12) and truth[-1, 2] < -9.9
    quat = flight.field("vehicle_attitude", "q")
    np.testing.assert_allclose(np.linalg.norm(quat, axis=1), 1.0, atol=1e-12)
    # 四元数逐字节保持写入值，读取端不做符号翻转或重排。
    np.testing.assert_array_equal(quat, sample["topics"]["vehicle_attitude"]["q"])
    assert quaternion_euler(quat).shape == (len(quat), 3)


def test_parameters_keep_effective_value_and_baseline(flight):
    rows = {row["path"]: row for row in flight.parameters}
    row = rows["controller.indi_output_filter_hz"]
    assert row["value"] == 15.0 and row["baseline_value"] == 8.0 and row["overridden"]
    assert flight.manifest["audit"]["original"]["status"] == "unknown"
    assert flight.manifest["execution"]["status"] == "completed"


def test_geometry_is_frd_with_six_vanes(flight):
    geometry = flight.geometry
    assert geometry["schema"] == "windtrace.geometry.v1" and geometry["frame"] == "FRD"
    hinges = np.asarray(geometry["vehicle"]["hinges_m"])
    assert hinges.shape == (6, 3)
    np.testing.assert_allclose(hinges[0], [-0.267, 0.0, 0.066], atol=1e-12)
    assert len(geometry["meshes"]["vanes"]) == 6
    assert len(geometry["meshes"]["body"]["points"]) > 3


def test_declared_width_matches_payload(flight):
    for name, spec in flight.manifest["topics"].items():
        topic = flight.topics[name]
        for field, desc in spec["fields"].items():
            array = np.asarray(topic[field]).reshape(len(topic["time_s"]), -1)
            assert array.shape[1] == desc["width"], f"{name}.{field}"


def test_non_wtr_suffix_rejected(tmp_path, sample):
    path = tmp_path / "flight.mat"
    path.write_bytes(b"not a container")
    with pytest.raises(FlightError, match="只接受"):
        read_flight(path)


@pytest.mark.parametrize("mutation", ["hash", "member", "schema", "time", "shape", "quat",
                                      "extra_field", "extra_topic", "timestamp"])
def test_invalid_contract_rejected(flight, tmp_path, mutation):
    def mutate(data):
        manifest = json.loads(data["manifest.json"])
        if mutation == "hash":
            data["geometry.json"] += b" "
            return
        if mutation == "member":
            data["../outside"] = b"bad"
            return
        if mutation == "schema":
            manifest["schema"] = "wrong"
        else:
            payload = loadmat(io.BytesIO(data["flight.mat"]), simplify_cells=True)
            if mutation == "time":
                payload["topics"]["shc09_indi"]["time_s"][1] = 0
            if mutation == "shape":
                payload["topics"]["shc09_indi"]["v_h"] = np.zeros((5, 2))
            if mutation == "quat":
                payload["topics"]["vehicle_attitude"]["q"] *= 2
            if mutation == "extra_field":
                payload["topics"]["shc09_indi"]["undeclared"] = np.zeros((5, 1))
            if mutation == "extra_topic":
                payload["topics"]["undeclared_topic"] = payload["topics"]["shc09_indi"]
            if mutation == "timestamp":
                payload["topics"]["shc09_indi"]["timestamp"] = payload["topics"]["shc09_indi"]["timestamp"] + 1
            buffer = io.BytesIO()
            savemat(buffer, {k: v for k, v in payload.items() if not k.startswith("__")},
                    long_field_names=True)
            data["flight.mat"] = buffer.getvalue()
            manifest["members"]["flight.mat"] = {"sha256": digest(data["flight.mat"]),
                                                 "bytes": len(data["flight.mat"])}
        data["manifest.json"] = json_bytes(manifest)

    with pytest.raises(FlightError):
        read_flight(rewrite(flight, tmp_path, mutate))


def test_duplicate_member_rejected(flight, tmp_path):
    path = tmp_path / "duplicate.wtr"
    path.write_bytes(flight.path.read_bytes())
    with zipfile.ZipFile(path, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr("manifest.json", b"{}")
    with pytest.raises(FlightError):
        read_flight(path)


def test_missing_required_topic_rejected(tmp_path, sample):
    topics = {name: value for name, value in sample["topics"].items() if name != "shc09_vanes"}
    specs = {name: value for name, value in sample["specs"].items() if name != "shc09_vanes"}
    path = write(tmp_path / "no_vanes.wtr", topics=topics, specs=specs,
                 parameters=sample["parameters"], duration_s=sample["duration_s"],
                 parameter_arrays=sample["parameter_arrays"])
    with pytest.raises(FlightError, match="核心topic"):
        read_flight(path)
