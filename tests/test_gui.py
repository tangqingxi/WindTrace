"""验证参数搜索、只读属性及多单飞行界面，不运行飞行仿真。"""
from pathlib import Path
import os

from PySide6 import QtCore, QtWidgets
import pytest

from core.flight import read_flight
from ui.main_window import MainWindow


def test_parameter_search_readonly_and_switch(tmp_path):
    paths=os.environ.get('WINDTRACE_TEST_FLIGHTS','').split(os.pathsep)
    if not paths or not paths[0]: pytest.skip('真实交付物由集成运行提供')
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings=QtCore.QSettings(str(tmp_path/'gui.ini'),QtCore.QSettings.Format.IniFormat)
    window=MainWindow(no_3d=True,settings=settings); window.load(paths); window.show(); app.processEvents()
    assert not window.left_drawer.isVisible() and not window.curve_drawer.isVisible()
    assert window.body.height()/window.height()>.85
    assert window.domain.count()==2 and window.domain.currentText()=='真实状态'
    assert window.grid_switch.isChecked() and not window.reference_switch.isChecked()
    assert window.camera_combo.count()==9 and window.camera_combo.currentData()=='follow'
    window.domain.setCurrentIndex(1); app.processEvents()
    assert window.domain.currentData()=='estimate'
    before=window.view.size()
    window.curve_button.setChecked(True); app.processEvents()
    assert window.curve_drawer.isVisible() and window.view.size()==before
    window.curve_button.setChecked(False)
    window.parameters.search.setText('controller.indi_output_filter_hz'); app.processEvents()
    table=window.parameters.table
    visible=[i for i in range(table.rowCount()) if not table.isRowHidden(i)]
    assert len(visible)==2
    assert table.editTriggers()==QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
    assert window.parameters.detail.isReadOnly()
    exact=next(i for i in visible if window.flight.parameters[i]['path']=='controller.indi_output_filter_hz')
    row=window.flight.parameters[exact]
    assert row['value']==15 and row['baseline_value']==8
    table.selectRow(exact); app.processEvents()
    assert '15' in window.parameters.detail.toPlainText()
    assert window.run_combo.count()==len(paths)
    window.run_combo.setCurrentIndex(1); app.processEvents()
    assert window.flight.run_id==window.flights[1].run_id
    assert 'original audit=' in window.info.text()
    window.field_combo.setCurrentText('vehicle_local_position.x [m]'); app.processEvents()
    assert len(window.plot.listDataItems())==len(paths)
    window.close(); app.processEvents()
