"""特殊数值和大数组在读取端必须原样可恢复，不能被悄悄替换成0或null。"""
import json

import numpy as np
import pytest

from core.flight import read_flight
from wtr_builder import hop_flight, write


@pytest.fixture
def flight(tmp_path):
    return read_flight(write(tmp_path / "parameters.wtr", **hop_flight()))


def test_special_floats_survive_read(flight):
    rows = {row["path"]: row for row in flight.parameters}
    assert rows["cfg.unbounded"]["value"] == {"special_float": "+Inf"}
    assert rows["cfg.missing_value"]["value"] == {"special_float": "NaN"}
    # 参数表整体必须是合法JSON：非有限数只能以带类型标记出现。
    json.dumps([row["value"] for row in flight.parameters], allow_nan=False)


def test_large_array_expands_to_full_values(flight):
    rows = {row["path"]: row for row in flight.parameters}
    assert rows["cfg.large"]["type"] == "array_ref"
    value = flight.parameter_value(rows["cfg.large"])
    np.testing.assert_array_equal(np.asarray(value), np.arange(240).reshape(80, 3))
    assert np.asarray(value).shape == (80, 3)
