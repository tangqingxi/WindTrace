"""播放按真实经过时间推进，不随帧率和整数滑块产生累计漂移。"""
import os
from PySide6 import QtCore, QtWidgets
import pytest
from ui.main_window import MainWindow


def test_wall_clock_without_rounding_drift(monkeypatch,tmp_path):
    source=os.environ.get('WINDTRACE_TEST_FLIGHTS','').split(os.pathsep)[0]
    if not source: pytest.skip('集成运行提供真实.wtr')
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings=QtCore.QSettings(str(tmp_path/'playback.ini'),QtCore.QSettings.Format.IniFormat)
    window=MainWindow(no_3d=True,settings=settings); window.load([source]); window.timer.stop()
    clock=[100.]; monkeypatch.setattr('ui.main_window.time.monotonic',lambda:clock[0])
    window.toggle_play()
    for i in range(601):
        clock[0]=100+i/60; window.advance()
    assert window._current_time==pytest.approx(10,abs=.004)
    assert window.slider.value()==round(10/window.flight.manifest['duration_s']*10000)
    window.toggle_play(); window.close(); app.processEvents()
