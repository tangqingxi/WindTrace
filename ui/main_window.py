"""以run_id选择单飞行；字段名、单位和参数值均来自交付物。"""
import json
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from core.flight import read_flight
from ui.camera import (CameraScriptError, analysis_script, load_camera_script,
                       showcase_script, vane_closeup_script)
from ui.view3d import ReplayView3D
from ui import theme
from ui.shell import Breadcrumb,SideRail,AccordionSection,AboutDialog
from ui.icons import icon


class ParameterTable(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(); self.flight=None
        layout=QtWidgets.QVBoxLayout(self)
        self.search=QtWidgets.QLineEdit(); self.search.setPlaceholderText("搜索参数完整路径、值、单位或来源…（只读）")
        layout.addWidget(self.search)
        self.table=QtWidgets.QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(["参数路径","此次生效值","单位","来源","父值","覆盖"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0,310); self.table.setColumnWidth(1,210); self.table.setColumnWidth(3,220)
        layout.addWidget(self.table)
        self.detail=QtWidgets.QPlainTextEdit(); self.detail.setReadOnly(True); self.detail.setMaximumHeight(140)
        layout.addWidget(self.detail); self.count=QtWidgets.QLabel(); layout.addWidget(self.count)
        copy=QtWidgets.QPushButton("复制选中参数的完整值"); layout.addWidget(copy); copy.clicked.connect(self.copy_value)
        self.search.textChanged.connect(self.filter); self.table.itemSelectionChanged.connect(self.show_value)

    def set_flight(self, flight):
        self.flight=flight; self.table.setRowCount(len(flight.parameters)); self.detail.clear()
        for i,row in enumerate(flight.parameters):
            value=json.dumps(row["value"],ensure_ascii=False)
            vals=[row["path"],value[:200],row["unit"],row["source"],json.dumps(row.get("baseline_value","未知"),ensure_ascii=False),"是" if row["overridden"] else "否"]
            for j,text in enumerate(vals):
                item=QtWidgets.QTableWidgetItem(text); item.setToolTip(text); self.table.setItem(i,j,item)
        self.filter(self.search.text())

    def filter(self, query):
        query=query.casefold(); count=0
        for i in range(self.table.rowCount()):
            hide=query not in " ".join(self.table.item(i,j).text() for j in range(6)).casefold()
            self.table.setRowHidden(i,hide); count+=not hide
        self.count.setText(f"{count}/{self.table.rowCount()} 个参数；只读，不回写文件")

    def show_value(self):
        i=self.table.currentRow()
        if self.flight is not None and i>=0:
            row=self.flight.parameters[i]
            value=self.flight.parameter_value(row)
            self.detail.setPlainText(json.dumps({**row,"value":value},ensure_ascii=False,indent=2))

    def copy_value(self):
        if self.table.currentRow()>=0:
            QtWidgets.QApplication.clipboard().setText(self.detail.toPlainText())


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, no_3d=False, settings=None):
        super().__init__(); self.setWindowTitle("风迹 WindTrace"); self.resize(1360,900); self.setMinimumSize(1000,700)
        self.flights=[]; self.flight=None; self.playing=False; self.clock=time.monotonic(); self._curve_height=None
        self._advancing=False; self._current_time=0.; self._last_curve_update=0.
        self.loading=False; self.last_error=''; self.last_camera_error=''; self._load_future=None; self._executor=None; self._closing=False
        self.settings=settings if settings is not None else QtCore.QSettings('SHC09','WindTrace')
        theme.apply_theme(QtWidgets.QApplication.instance())
        pg.setConfigOptions(foreground=theme.COLORS['secondary'],antialias=False)
        central=QtWidgets.QWidget(); central.setObjectName("central"); self.setCentralWidget(central)
        root=QtWidgets.QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        top=QtWidgets.QFrame(); top.setObjectName("topBar"); top.setFixedHeight(theme.HEIGHTS["top"])
        bar=QtWidgets.QHBoxLayout(top); bar.setContentsMargins(16,0,16,0); bar.setSpacing(8)
        logo=QtWidgets.QLabel(); logo.setPixmap(QtGui.QPixmap(str(Path(__file__).parents[1]/"assets/logo_32.png"))); logo.setFixedSize(32,32); bar.addWidget(logo)
        title=QtWidgets.QLabel("风迹"); title.setObjectName("appName"); bar.addWidget(title)
        version=QtWidgets.QLabel(f"v{theme.APP_VERSION}"); version.setObjectName("appVersion"); bar.addWidget(version)
        separator=QtWidgets.QFrame(); separator.setObjectName("separator"); separator.setFixedHeight(24); bar.addWidget(separator)
        self.breadcrumb=Breadcrumb(); self.breadcrumb.set_segments(["单飞行",".wtr","—","—"]); bar.addWidget(self.breadcrumb); bar.addStretch(1)
        self.open_button=QtWidgets.QPushButton("打开"); self.open_button.clicked.connect(self.open_dialog); bar.addWidget(self.open_button)
        reload=QtWidgets.QPushButton("重载"); reload.clicked.connect(self.reload); bar.addWidget(reload)
        self.reload_button=reload
        self.png=QtWidgets.QPushButton("导出 PNG"); self.png.setObjectName("ghostAction"); self.png.setIcon(icon('download')); self.png.setToolTip("把当前视图导出为 PNG"); self.png.clicked.connect(self.export_png); bar.addWidget(self.png)
        help_button=QtWidgets.QToolButton(); help_button.setObjectName("helpButton"); help_button.setText("帮助"); help_button.clicked.connect(lambda:AboutDialog(self).exec()); bar.addWidget(help_button)
        root.addWidget(top)
        self.body=QtWidgets.QWidget(); self.body.setObjectName("viewHolder"); body_layout=QtWidgets.QVBoxLayout(self.body); body_layout.setContentsMargins(0,0,0,0)
        self.view=ReplayView3D(disabled=no_3d); body_layout.addWidget(self.view); root.addWidget(self.body,1)
        self.welcome=QtWidgets.QFrame(self.body); self.welcome.setObjectName('leftDrawer'); self.welcome.setFixedWidth(420)
        welcome_layout=QtWidgets.QVBoxLayout(self.welcome); welcome_layout.setContentsMargins(24,24,24,24); welcome_layout.setSpacing(12)
        self.welcome.installEventFilter(self)
        self.welcome_title=QtWidgets.QLabel('打开一份飞行日志'); self.welcome_title.setFont(theme.font('app',bold=True)); welcome_layout.addWidget(self.welcome_title)
        self.welcome_hint=QtWidgets.QLabel('双击最近日志打开，或选择单飞行 .wtr 文件开始查看。'); self.welcome_hint.setWordWrap(True); self.welcome_hint.setProperty('muted',True); welcome_layout.addWidget(self.welcome_hint)
        self.recent_title=QtWidgets.QLabel('最近日志'); self.recent_title.setProperty('muted',True); welcome_layout.addWidget(self.recent_title)
        self.recent_list=QtWidgets.QListWidget(); self.recent_list.setObjectName('recentList')
        self.recent_list.setMaximumHeight(236); self.recent_list.setMinimumHeight(0); self.recent_list.setUniformItemSizes(False)
        self.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.recent_list.itemActivated.connect(self._activate_recent)
        self.recent_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.recent_list.customContextMenuRequested.connect(self._recent_menu)
        self.recent_list.setToolTip('双击打开；右键可从列表移除')
        welcome_layout.addWidget(self.recent_list)
        self.recent_empty=QtWidgets.QLabel('尚无最近日志。'); self.recent_empty.setProperty('muted',True); welcome_layout.addWidget(self.recent_empty)
        self.load_progress=QtWidgets.QProgressBar(); self.load_progress.setRange(0,0); self.load_progress.setTextVisible(False); self.load_progress.setFixedHeight(5); self.load_progress.hide(); welcome_layout.addWidget(self.load_progress)
        self.welcome_open=QtWidgets.QPushButton('打开飞行日志…'); self.welcome_open.setObjectName('primary'); self.welcome_open.setProperty('welcomeAction',True); self.welcome_open.clicked.connect(self.open_dialog); welcome_layout.addWidget(self.welcome_open)
        self.welcome_back=QtWidgets.QPushButton('返回当前飞行'); self.welcome_back.setProperty('welcomeAction',True); self.welcome_back.clicked.connect(self.welcome.hide); self.welcome_back.hide(); welcome_layout.addWidget(self.welcome_back)
        bottom=QtWidgets.QFrame(); bottom.setObjectName("bottomBar"); bottom.setFixedHeight(theme.HEIGHTS["bottom"])
        timeline=QtWidgets.QHBoxLayout(bottom); timeline.setContentsMargins(16,0,16,0); timeline.setSpacing(8)
        self.play=QtWidgets.QPushButton("▶"); self.play.setObjectName("iconButton"); self.play.setFixedWidth(32); self.play.clicked.connect(self.toggle_play); timeline.addWidget(self.play)
        reset=QtWidgets.QPushButton("↺"); reset.setObjectName("iconButton"); reset.setFixedWidth(32); reset.clicked.connect(lambda:self.slider.setValue(0)); timeline.addWidget(reset)
        self.slider=QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.slider.setRange(0,10000); self.slider.valueChanged.connect(self.seek); timeline.addWidget(self.slider,1)
        self.time_label=QtWidgets.QLabel("t = —"); self.time_label.setObjectName("timeLabel"); self.time_label.setMinimumWidth(210); self.time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight|QtCore.Qt.AlignmentFlag.AlignVCenter); timeline.addWidget(self.time_label)
        self.speed=QtWidgets.QComboBox(); self.speed.addItems(["0.25×","0.5×","1×","2×"]); self.speed.setCurrentIndex(2); self.speed.setFixedWidth(76); timeline.addWidget(self.speed)
        self.curve_button=QtWidgets.QPushButton("曲线 ▴"); self.curve_button.setObjectName("curveToggle"); self.curve_button.setCheckable(True); self.curve_button.toggled.connect(self.toggle_curves); timeline.addWidget(self.curve_button)
        root.addWidget(bottom)
        self.rail=SideRail(self.body); self.rail.sectionClicked.connect(lambda _:self.toggle_drawer()); self.rail.closeClicked.connect(lambda:self.left_drawer.hide())
        self.left_drawer=QtWidgets.QFrame(self.body); self.left_drawer.setObjectName("leftDrawer"); self.left_drawer.setFixedWidth(220); self.left_drawer.hide()
        drawer=QtWidgets.QVBoxLayout(self.left_drawer); drawer.setContentsMargins(12,12,12,12); drawer.setSpacing(8)
        head=QtWidgets.QHBoxLayout(); label=QtWidgets.QLabel("参数"); label.setObjectName("groupTitle"); head.addWidget(label); head.addStretch()
        close=QtWidgets.QToolButton(); close.setText("«"); close.setObjectName("collapseButton"); close.clicked.connect(self.left_drawer.hide); head.addWidget(close); drawer.addLayout(head)
        scroll=QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        content=QtWidgets.QWidget(); content.setMinimumWidth(1); content_layout=QtWidgets.QVBoxLayout(content); content_layout.setContentsMargins(0,0,0,0); content_layout.setSpacing(8)
        scroll.setWidget(content); drawer.addWidget(scroll,1)
        data=AccordionSection("数据"); content_layout.addWidget(data)
        self.run_combo=QtWidgets.QComboBox(); self.run_combo.setMinimumWidth(0)
        self.run_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.run_combo.setMinimumContentsLength(10)
        self.run_combo.currentIndexChanged.connect(self.select_flight); data.content_layout.addWidget(self.run_combo)
        parameters_button=QtWidgets.QPushButton("查看飞行参数…"); data.content_layout.addWidget(parameters_button)
        self.info=QtWidgets.QLabel("打开独立.wtr飞行日志"); self.info.setWordWrap(True); self.info.setProperty("muted",True); data.content_layout.addWidget(self.info)
        display=AccordionSection("显示"); content_layout.addWidget(display)
        basis=QtWidgets.QLabel("显示状态"); basis.setProperty("muted",True); display.content_layout.addWidget(basis)
        self.domain=QtWidgets.QComboBox()
        for label,key in [("真实状态","truth"),("估计状态","estimate")]: self.domain.addItem(label,key)
        self.domain.setToolTip("真实状态：实际位置与姿态；估计状态：机载估计器认为的位置与姿态。只改变显示。")
        self.domain.currentIndexChanged.connect(self.change_domain); display.content_layout.addWidget(self.domain)
        self.refresh=QtWidgets.QComboBox(); self.refresh.addItem('流畅回放',16); self.refresh.addItem('节能回放',33)
        self.refresh.setToolTip('流畅：约60次/秒；节能：约30次/秒。曲线游标单独限频。')
        self.refresh.currentIndexChanged.connect(lambda _:self.timer.setInterval(self.refresh.currentData())); display.content_layout.addWidget(self.refresh)
        frame=QtWidgets.QLabel("SHC09"); frame.setProperty("muted",True); display.content_layout.addWidget(frame)
        scene=AccordionSection("场景"); content_layout.addWidget(scene)
        world_title=QtWidgets.QLabel("世界坐标系"); world_title.setProperty("muted",True); scene.content_layout.addWidget(world_title)
        self.world_frame_combo=QtWidgets.QComboBox()
        self.world_frame_combo.addItem("NED（北东地，默认）","NED")
        self.world_frame_combo.addItem("ENU（东北天）","ENU")
        self.world_frame_combo.setToolTip("只改变三维显示与读数的世界系；日志仍为 NED，不写回文件。")
        frame=str(self.settings.value('scene/world_frame','NED') or 'NED')
        index=self.world_frame_combo.findData(frame)
        self.world_frame_combo.setCurrentIndex(index if index>=0 else 0)
        self.world_frame_combo.currentIndexChanged.connect(self._world_frame_changed)
        scene.content_layout.addWidget(self.world_frame_combo)
        self.view.set_world_frame(self.world_frame_combo.currentData())
        self.body_frame_switch=QtWidgets.QCheckBox("显示机体坐标系"); self.body_frame_switch.setChecked(False)
        self.body_frame_switch.setToolTip("真实b系：b1红向右(+y_FRD)、b2绿向下(−x_FRD)、b3蓝入纸(+z_FRD)；FRD绕z转90°，右手系，仅显示。")
        self.body_frame_switch.toggled.connect(self.view.set_body_frame_visible)
        scene.content_layout.addWidget(self.body_frame_switch)
        self.grid_switch=QtWidgets.QCheckBox("显示地面网格"); self.grid_switch.setChecked(True); self.grid_switch.toggled.connect(self.view.set_grid_visible); scene.content_layout.addWidget(self.grid_switch)
        self.reference_switch=QtWidgets.QCheckBox("显示参考轨迹"); self.reference_switch.setChecked(False); self.reference_switch.toggled.connect(self.view.set_reference_visible); scene.content_layout.addWidget(self.reference_switch)
        self.rotor_switch=QtWidgets.QCheckBox("螺旋桨转动"); self.rotor_switch.setChecked(True); self.rotor_switch.setToolTip('显示用名义转速，不是实测RPM；日志没有转速字段。'); self.rotor_switch.toggled.connect(self.view.set_rotor_spinning); scene.content_layout.addWidget(self.rotor_switch)
        self.ground_projection_switch=QtWidgets.QCheckBox("地面投影"); self.ground_projection_switch.setChecked(True); self.ground_projection_switch.setToolTip('从机体向地面画垂线和落点环，便于读高度与水平位置。'); self.ground_projection_switch.toggled.connect(self.view.set_ground_projection); scene.content_layout.addWidget(self.ground_projection_switch)
        self.reference_error_switch=QtWidgets.QCheckBox("参考误差线"); self.reference_error_switch.setChecked(True); self.reference_error_switch.setToolTip('在当前参考点画标记，并连到机体中心；显示三轴跟踪差异。'); self.reference_error_switch.toggled.connect(self.view.set_reference_error); scene.content_layout.addWidget(self.reference_error_switch)
        camera_title=QtWidgets.QLabel("相机模式"); camera_title.setProperty("muted",True); scene.content_layout.addWidget(camera_title)
        self.camera_combo=QtWidgets.QComboBox()
        for label,key in [("跟随（默认）","follow"),("自由视角","free"),("追尾","chase"),("环绕","orbit"),("总览","overview"),("机体特写","closeup")]:
            self.camera_combo.addItem(label,key)
        self.camera_combo.addItem("演示 · 发布镜头",('preset','showcase'))
        self.camera_combo.addItem("对比 · 固定机位",('preset','analysis'))
        self.camera_combo.addItem("特写 · 舵面",('preset','closeup'))
        self.camera_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.camera_combo.setMinimumContentsLength(10)
        self.camera_combo.setToolTip("相机只改变观察方式，不参与控制或评价。鼠标拖动会切到自由视角。")
        self.camera_combo.currentIndexChanged.connect(self._camera_changed)
        scene.content_layout.addWidget(self.camera_combo)
        self.import_camera=QtWidgets.QPushButton("导入运镜…"); self.import_camera.clicked.connect(self.import_camera_dialog); scene.content_layout.addWidget(self.import_camera)
        self.remove_camera=QtWidgets.QPushButton("移除运镜"); self.remove_camera.setEnabled(False); self.remove_camera.clicked.connect(self.remove_camera_script); scene.content_layout.addWidget(self.remove_camera)
        self.ground_hint=QtWidgets.QLabel("机体底点贴地：按加载日志的几何计算"); self.ground_hint.setProperty("muted",True); self.ground_hint.setWordWrap(True); scene.content_layout.addWidget(self.ground_hint)
        source=QtWidgets.QPushButton("来源与审计…"); scene.content_layout.addWidget(source); content_layout.addStretch(1)
        shadow=QtWidgets.QGraphicsDropShadowEffect(self.left_drawer); shadow.setBlurRadius(12); shadow.setOffset(2,0); shadow.setColor(QtGui.QColor(17,24,39,42)); self.left_drawer.setGraphicsEffect(shadow)
        self.parameters=ParameterTable(); self.parameters_dialog=QtWidgets.QDialog(self); self.parameters_dialog.setWindowTitle("飞行参数 · 只读"); self.parameters_dialog.resize(1100,720)
        parameter_layout=QtWidgets.QVBoxLayout(self.parameters_dialog); parameter_layout.addWidget(self.parameters)
        parameters_button.clicked.connect(self.show_parameters)
        self.metadata=QtWidgets.QPlainTextEdit(); self.metadata.setReadOnly(True)
        self.source_dialog=QtWidgets.QDialog(self); self.source_dialog.setWindowTitle("飞行来源与原始审计"); self.source_dialog.resize(900,680); meta_layout=QtWidgets.QVBoxLayout(self.source_dialog); meta_layout.addWidget(self.metadata)
        source.clicked.connect(self.source_dialog.show)
        self.curve_drawer=QtWidgets.QFrame(self.body); self.curve_drawer.setObjectName("curveDrawer"); self.curve_drawer.hide()
        cl=QtWidgets.QVBoxLayout(self.curve_drawer); cl.setContentsMargins(16,0,16,8); cl.setSpacing(8)
        self.curve_grip=QtWidgets.QFrame(); self.curve_grip.setObjectName("curveGrip"); self.curve_grip.setFixedHeight(6); self.curve_grip.setCursor(QtCore.Qt.CursorShape.SizeVerCursor); self.curve_grip.installEventFilter(self); cl.addWidget(self.curve_grip)
        curve_head=QtWidgets.QHBoxLayout(); heading=QtWidgets.QLabel("飞行曲线"); heading.setObjectName("curveTitle"); curve_head.addWidget(heading)
        self.field_combo=QtWidgets.QComboBox(); self.field_combo.currentTextChanged.connect(self.plot_field); self.field_combo.setMinimumWidth(300); curve_head.addWidget(self.field_combo,1)
        hint=QtWidgets.QLabel("PX4字段 · 原生时间轴"); hint.setObjectName("curveHint"); curve_head.addWidget(hint)
        hide=QtWidgets.QToolButton(); hide.setText("×"); hide.setObjectName("drawerClose"); hide.clicked.connect(lambda:self.curve_button.setChecked(False)); curve_head.addWidget(hide); cl.addLayout(curve_head)
        self.plot=pg.PlotWidget(background=theme.COLORS['surface']); self.plot.addLegend(); self.plot.showGrid(x=True,y=True,alpha=.14); self.plot.plotItem.hideButtons(); cl.addWidget(self.plot)
        for name in ['left','bottom']:
            axis=self.plot.getAxis(name); axis.setPen(pg.mkPen(theme.COLORS['muted'])); axis.setTextPen(pg.mkPen(theme.COLORS['muted']))
        self.cursor=pg.InfiniteLine(angle=90,movable=False,pen=pg.mkPen(theme.COLORS['muted'],style=QtCore.Qt.PenStyle.DashLine))
        for key,action in [('Tab',self.toggle_drawer),('C',lambda:self.curve_button.toggle()),('Escape',self.close_drawers),('Space',self.toggle_play),('Home',lambda:self.slider.setValue(0)),('Ctrl+O',self.open_dialog)]:
            shortcut=QtGui.QShortcut(QtGui.QKeySequence(key),self); shortcut.activated.connect(action)
        self.timer=QtCore.QTimer(self); self.timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer); self.timer.setInterval(16); self.timer.timeout.connect(self.advance); self.timer.start()
        self.speed.currentTextChanged.connect(self.rebase_playback)
        self.play.setText(''); self.play.setIcon(icon('play')); self.play.setToolTip('播放 / 暂停（空格）')
        reset.setText(''); reset.setIcon(icon('reset')); reset.setToolTip('回到0秒')
        self.rail._buttons['data'].setText(''); self.rail._buttons['data'].setIcon(icon('menu'))
        self.curve_button.setText('曲线'); self.curve_button.setIcon(icon('up'))
        self.load_poll=QtCore.QTimer(self); self.load_poll.setInterval(40); self.load_poll.timeout.connect(self._poll_load)
        self.view.cameraInteracted.connect(self._on_camera_interacted)
        self._restore_camera_preferences()
        self._refresh_recent_list()
        self._set_controls_ready(False); self.timer.stop()

    def position_drawers(self):
        if not hasattr(self,'rail'): return
        width,height=self.body.width(),self.body.height()
        # 固定卡片宽度，按可见内容计算高度，避免空白撑大或长错误信息撑宽。
        welcome_layout=self.welcome.layout()
        card_height=welcome_layout.totalHeightForWidth(self.welcome.width())
        computed=card_height if card_height>=0 else welcome_layout.sizeHint().height()
        self.welcome.setFixedHeight(min(max(160,height-32),max(160,computed)))
        self.rail.setGeometry(0,0,36,height); self.rail.raise_()
        self.left_drawer.setGeometry(44,12,220,max(200,height-24))
        self.view.set_badge_margin(280 if self.left_drawer.isVisible() else 48)
        h=self._curve_height or min(560,max(360,round(height*.42)))
        self.curve_drawer.setGeometry(36,max(0,height-h),max(1,width-36),min(height,h))
        if self.left_drawer.isVisible(): self.left_drawer.raise_()
        if self.curve_drawer.isVisible(): self.curve_drawer.raise_()
        self.welcome.move(max(40,(width-self.welcome.width())//2),max(12,(height-self.welcome.height())//2))
        if self.welcome.isVisible(): self.welcome.raise_()

    def resizeEvent(self,event):
        super().resizeEvent(event); QtCore.QTimer.singleShot(0,self.position_drawers)

    def showEvent(self,event):
        super().showEvent(event)
        # 等待布局计算完毕再居中首次打开提示。
        QtCore.QTimer.singleShot(0,self.position_drawers)

    def toggle_drawer(self):
        self.left_drawer.setVisible(not self.left_drawer.isVisible()); self.rail.set_active('data' if self.left_drawer.isVisible() else None); self.position_drawers()

    def toggle_curves(self,show):
        if show and (self.flight is None or self.loading):
            self.curve_button.blockSignals(True); self.curve_button.setChecked(False); self.curve_button.blockSignals(False); return
        self.curve_drawer.setVisible(show); self.curve_button.setText('曲线'); self.curve_button.setIcon(icon('down' if show else 'up')); self.position_drawers()
        if show and hasattr(self,'cursor'): self.cursor.setValue(self._current_time)

    def close_drawers(self):
        self.left_drawer.hide(); self.curve_button.setChecked(False)

    def show_parameters(self):
        if self.flight is None: return
        self.parameters_dialog.show(); self.parameters_dialog.raise_()

    def eventFilter(self,obj,event):
        if obj is getattr(self,'welcome',None) and event.type()==QtCore.QEvent.Type.Resize:
            QtCore.QTimer.singleShot(0,self.position_drawers)
        if obj is getattr(self,'curve_grip',None):
            if event.type()==QtCore.QEvent.Type.MouseButtonPress:
                self._drag_start=event.globalPosition().y(); self._drag_height=self.curve_drawer.height(); return True
            if event.type()==QtCore.QEvent.Type.MouseMove and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                self._curve_height=max(240,min(self.body.height()-50,round(self._drag_height+self._drag_start-event.globalPosition().y()))); self.position_drawers(); return True
        return super().eventFilter(obj,event)

    def reload(self):
        if self.flight: self.load_async([self.flight.path],remember=True)

    def load(self, paths):
        loaded=[read_flight(path) for path in paths]
        self._apply_loaded(loaded)

    def _apply_loaded(self,loaded):
        first=None
        self.run_combo.blockSignals(True)
        for f in loaded:
            index=next((i for i,x in enumerate(self.flights) if x.run_id==f.run_id),None)
            label=f"{f.manifest['method']} · s{f.manifest['seed']} · {f.path.name}"
            if index is None:
                index=len(self.flights); self.flights.append(f); self.run_combo.addItem(label)
            else:
                self.flights[index]=f; self.run_combo.setItemText(index,label)
            if first is None: first=index
        self.run_combo.blockSignals(False)
        if first is not None:
            self.run_combo.blockSignals(True); self.run_combo.setCurrentIndex(first); self.run_combo.blockSignals(False)
            self.select_flight(first)

    def _set_controls_ready(self,ready):
        for widget in [self.play,self.slider,self.speed,self.curve_button,self.png,self.reload_button]: widget.setEnabled(ready)

    def load_async(self,paths,remember=True):
        if self.loading or not paths or self._closing: return
        paths=[Path(p) for p in paths]; self.loading=True; self.last_error=''; self._remember_load=remember
        self.playing=False; self.play.setIcon(icon('play')); self.timer.stop(); self._set_controls_ready(False)
        self.open_button.setEnabled(False); self.welcome_open.hide(); self.welcome_back.hide()
        self.welcome_title.setText('正在加载飞行日志'); self.welcome_hint.setText('读取并校验 '+paths[0].name+(' 等文件' if len(paths)>1 else '')+'…')
        self.load_progress.show(); self.welcome.show(); self.position_drawers()
        if self._executor is None: self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='WindTraceReader')
        # 工作线程只读数值容器；Qt控件和VTK场景始终留在主线程更新。
        self._load_future=self._executor.submit(lambda:[read_flight(path) for path in paths]); self.load_poll.start()

    def _poll_load(self):
        if self._load_future is None or not self._load_future.done(): return
        future=self._load_future; self._load_future=None; self.load_poll.stop()
        if self._closing: return
        try:
            loaded=future.result(); self.welcome_hint.setText('日志校验完成，正在准备三维视图…')
            # 一个窗口只保留一份飞行；对比请另开 WindTrace 窗口。
            self.flights=[]; self.run_combo.blockSignals(True); self.run_combo.clear(); self.run_combo.blockSignals(False)
            self._apply_loaded(loaded)
            if self._remember_load and self.flight:
                self._remember_recent(self.flight)
            if getattr(self,'pending_camera_file',None):
                self.load_camera_file(self.pending_camera_file); self.pending_camera_file=None
            self.last_error=''; self.welcome.hide()
        except Exception as problem:
            self.last_error=str(problem); self.welcome_title.setText('日志未能打开')
            self.welcome_hint.setText(self.last_error[:350]); self.welcome_open.setText('重新选择日志…'); self.welcome.show()
            self.welcome_back.setVisible(self.flight is not None)
        finally:
            self.loading=False; self.load_progress.hide(); self.welcome_open.show(); self.open_button.setEnabled(True)
            self.position_drawers()
            self._set_controls_ready(self.flight is not None)
            if self.flight is not None: self.timer.start()

    # ------------------------------------------------------------ 最近日志
    def _recent_entries(self):
        raw=self.settings.value('recent_files','')
        data=[]
        if isinstance(raw,str) and raw.strip():
            try: data=json.loads(raw)
            except (ValueError,TypeError): data=[]
        elif isinstance(raw,list): data=raw
        if not isinstance(data,list): data=[]
        entries=[entry for entry in data if isinstance(entry,dict) and entry.get('path')]
        if not entries:
            old=self.settings.value('recent_file','')
            if isinstance(old,str) and old: entries=[{'path':old}]
        return entries[:8]

    def _save_recent_entries(self,entries):
        self.settings.setValue('recent_files',json.dumps(entries[:8],ensure_ascii=False))
        self.settings.sync()

    def _remember_recent(self,flight):
        path=str(flight.path.resolve()); manifest=flight.manifest
        entry={'path':path,'method':manifest.get('method'),'seed':manifest.get('seed'),
               'duration_s':manifest.get('duration_s'),'saved_at':time.strftime('%Y-%m-%dT%H:%M:%S')}
        entries=[entry for entry in self._recent_entries() if entry.get('path')!=path]
        entries.insert(0,entry); self._save_recent_entries(entries[:8])
        self.settings.setValue('recent_file',path)
        self.settings.setValue('recent_directory',str(flight.path.resolve().parent)); self.settings.sync()
        self._refresh_recent_list()

    def _refresh_recent_list(self):
        if not hasattr(self,'recent_list'): return
        entries=self._recent_entries(); self.recent_list.clear()
        for entry in entries:
            path=str(entry.get('path','')); missing=not Path(path).is_file()
            item=QtWidgets.QListWidgetItem(); item.setData(QtCore.Qt.ItemDataRole.UserRole,path)
            item.setToolTip(path+('\n文件不存在' if missing else '\n双击打开'))
            item.setSizeHint(QtCore.QSize(0,60)); self.recent_list.addItem(item)
            row=QtWidgets.QWidget(); row.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay=QtWidgets.QVBoxLayout(row); lay.setContentsMargins(8,4,8,4); lay.setSpacing(2)
            head=QtWidgets.QHBoxLayout(); head.setSpacing(8)
            name=QtWidgets.QLabel(Path(path).name); name.setFont(theme.font('app',bold=True))
            if missing: name.setStyleSheet(f"color:{theme.COLORS['danger']};")
            head.addWidget(name); head.addStretch(1)
            if missing:
                badge=QtWidgets.QLabel('文件不存在'); badge.setProperty('warn',True); head.addWidget(badge)
            lay.addLayout(head)
            meta=QtWidgets.QHBoxLayout(); meta.setSpacing(12)
            for text in [entry.get('method'),f"seed {entry.get('seed')}" if entry.get('seed') is not None else None,
                         f"{entry.get('duration_s'):g} s" if isinstance(entry.get('duration_s'),(int,float)) else None]:
                if text:
                    label=QtWidgets.QLabel(str(text)); label.setProperty('muted',True); meta.addWidget(label)
            meta.addStretch(1); lay.addLayout(meta)
            short=QtWidgets.QLabel(); short.setProperty('muted',True); short.setToolTip(path)
            short.setText(QtGui.QFontMetrics(short.font()).elidedText(path,QtCore.Qt.TextElideMode.ElideMiddle,320))
            lay.addWidget(short)
            self.recent_list.setItemWidget(item,row)
        self.recent_empty.setVisible(not entries); self.recent_title.setVisible(bool(entries))
        if not self.last_error and self.flight is None:
            self.welcome_hint.setText('双击最近日志打开，或选择单飞行 .wtr 文件开始查看。' if entries
                                      else '尚未加载飞行日志。请选择单飞行 .wtr 文件开始查看。')
        if entries:
            self.recent_list.show(); self.recent_list.setMaximumHeight(min(236,60*min(len(entries),4)+4))
        else:
            self.recent_list.hide()
        if hasattr(self,'welcome'): self.position_drawers()

    def _activate_recent(self,item):
        if item is None or self.loading: return
        path=Path(str(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        if not path.is_file():
            self.welcome_title.setText('最近日志不可用')
            self.welcome_hint.setText(f'文件已移动或删除：{path}\n请点击“打开飞行日志…”重新选择。')
            self.welcome.show(); self.position_drawers()
            return
        self.load_async([path])

    def _recent_menu(self,pos):
        menu=QtWidgets.QMenu(self)
        item=self.recent_list.itemAt(pos)
        remove=menu.addAction('从列表移除'); remove.setEnabled(item is not None)
        clear=menu.addAction('清空最近列表')
        chosen=menu.exec(self.recent_list.mapToGlobal(pos))
        if chosen is remove: self._remove_recent(item)
        elif chosen is clear: self._save_recent_entries([]); self._refresh_recent_list()

    def _remove_recent(self,item):
        if item is None: return
        path=str(item.data(QtCore.Qt.ItemDataRole.UserRole))
        self._save_recent_entries([entry for entry in self._recent_entries() if entry.get('path')!=path])
        self._refresh_recent_list()

    def show_welcome(self):
        self._refresh_recent_list()
        self.welcome_title.setText('打开一份飞行日志')
        self.welcome_hint.setText('双击最近日志打开，或选择单飞行 .wtr 文件开始查看。')
        self.welcome_open.setText('打开飞行日志…'); self.welcome_open.show()
        self.welcome_back.setVisible(self.flight is not None)
        self.welcome.show(); self.position_drawers()

    # -------------------------------------------------------------- 相机与运镜
    def _find_camera_data(self,data):
        for index in range(self.camera_combo.count()):
            if self.camera_combo.itemData(index)==data: return index
        return -1

    def _world_frame_changed(self,index=None):
        frame=self.world_frame_combo.currentData()
        if not frame: return
        self.view.set_world_frame(frame)
        self.settings.setValue('scene/world_frame',frame); self.settings.sync()

    def _camera_changed(self,index=None):
        data=self.camera_combo.currentData()
        if isinstance(data,tuple) and data and data[0]=='script':
            script=data[1]
            self.view.set_camera_mode('script',script,animate=not self.view.offscreen)
            self.settings.setValue('camera/mode','script'); self.settings.setValue('camera/script',script.source); self.settings.sync()
            self.remove_camera.setEnabled(True)
        elif isinstance(data,tuple) and data and data[0]=='preset':
            duration=float(self.flight.manifest['duration_s']) if self.flight is not None else 55.0
            builders={'showcase':showcase_script,'analysis':analysis_script,'closeup':vane_closeup_script}
            script=builders[data[1]](duration)
            self.view.set_camera_mode('script',script,animate=not self.view.offscreen)
            self.settings.setValue('camera/mode','preset:'+data[1]); self.settings.sync()
            self.remove_camera.setEnabled(False)
            if data[1]=='analysis':
                self.ground_projection_switch.setChecked(True)
                self.reference_error_switch.setChecked(True)
            elif data[1]=='closeup':
                self.ground_projection_switch.setChecked(False)
                self.reference_error_switch.setChecked(False)
        elif isinstance(data,str):
            self.view.set_camera_mode(data,animate=not self.view.offscreen)
            self.settings.setValue('camera/mode',data); self.settings.sync()
            self.remove_camera.setEnabled(False)

    def _apply_camera_choice(self):
        if self.flight is not None: self._camera_changed()

    def select_camera_mode(self,name):
        index=self.camera_combo.findData(name)
        if index>=0: self.camera_combo.setCurrentIndex(index)

    def select_camera_preset(self,name):
        index=self._find_camera_data(('preset',name))
        if index>=0: self.camera_combo.setCurrentIndex(index)

    def _on_camera_interacted(self):
        if self.flight is None or self.loading: return
        if self.camera_combo.currentData()=='free': return
        index=self.camera_combo.findData('free')
        if index<0: return
        self.camera_combo.blockSignals(True); self.camera_combo.setCurrentIndex(index); self.camera_combo.blockSignals(False)
        self.view.set_camera_mode('free'); self.remove_camera.setEnabled(False)
        self.settings.setValue('camera/mode','free'); self.settings.sync()

    def _restore_camera_preferences(self):
        mode=str(self.settings.value('camera/mode','follow') or 'follow')
        source=self.settings.value('camera/script','') or ''
        if mode.startswith('preset:'):
            key=mode.split(':',1)[1]
            index=self._find_camera_data(('preset',key))
            if index<0: index=self.camera_combo.findData('follow')
        elif source and Path(str(source)).is_file():
            try:
                self._add_camera_script(load_camera_script(source),select=False)
                index=self.camera_combo.count()-1 if mode=='script' else self.camera_combo.findData(mode)
            except CameraScriptError:
                index=self.camera_combo.findData('follow')
        else:
            index=self.camera_combo.findData(mode)
        if index<0: index=self.camera_combo.findData('follow')
        self.camera_combo.blockSignals(True); self.camera_combo.setCurrentIndex(index); self.camera_combo.blockSignals(False)

    def import_camera_dialog(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,"导入运镜脚本",str(Path.home()),"运镜 (*.json *.wtcam);;JSON (*.json)")
        if path: self.load_camera_file(path,announce=True)

    def load_camera_file(self,path,announce=False):
        try:
            script=load_camera_script(path)
        except CameraScriptError as problem:
            self.last_camera_error=str(problem)
            if announce: QtWidgets.QMessageBox.warning(self,'运镜文件不可用',str(problem))
            return False
        self.last_camera_error=''; self._add_camera_script(script,select=True); return True

    def _add_camera_script(self,script,select=True):
        for index in range(self.camera_combo.count()):
            data=self.camera_combo.itemData(index)
            if isinstance(data,tuple) and data and data[0]=='script' and data[1].name==script.name:
                self.camera_combo.removeItem(index); break
        self.camera_combo.addItem(f"运镜 · {script.name}",('script',script))
        if select:
            self.camera_combo.setCurrentIndex(self.camera_combo.count()-1)

    def remove_camera_script(self):
        data=self.camera_combo.currentData()
        if not (isinstance(data,tuple) and data and data[0]=='script'): return
        self.camera_combo.removeItem(self.camera_combo.currentIndex())
        index=self.camera_combo.findData('follow')
        self.camera_combo.setCurrentIndex(max(0,index))
        self.settings.remove('camera/script'); self.settings.sync()

    def _update_scene_hint(self):
        if self.flight is None:
            self.ground_hint.setText('机体底点贴地：按加载日志的几何计算'); return
        lift=float(getattr(self.view,'ground_lift_m',0.0))
        self.ground_hint.setText(f'机体底点贴地：+{lift:.3f} m（仅显示，不改变日志数值）')

    def open_dialog(self):
        if self.loading: return
        directory=self.settings.value('recent_directory','')
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,"打开单飞行交付物",directory,"飞行日志 (*.wtr)")
        if path: self.load_async([Path(path)])

    def select_flight(self,index):
        if not 0<=index<len(self.flights): return
        previous_time=float(self._current_time) if self.flight is not None else 0.0
        self.flight=self.flights[index]; f=self.flight; m=f.manifest
        duration=max(float(m['duration_s']),1e-6); target=min(max(previous_time,0.0),duration)
        self.playing=False; self.play.setIcon(icon('play'))
        self.slider.blockSignals(True); self.slider.setValue(round(target/duration*10000)); self.slider.blockSignals(False)
        self._current_time=target
        original=m["audit"]["original"].get("status","unknown")
        self.info.setText(f"{m['scenario']} | {m['method']} | seed {m['seed']} | {m['duration_s']:g}s | execution={m['execution']['status']} | original audit={original}")
        self.metadata.setPlainText(json.dumps(m,ensure_ascii=False,indent=2)); self.parameters.set_flight(f)
        case="hover_distance" if "HOVER" in str(m["scenario"]).upper() or "滚转" in str(m["scenario"]) else str(m["scenario"])
        self.breadcrumb.set_segments([case,".wtr",m["method"],f"s{m['seed']}"]); self.breadcrumb.set_path_tooltip(str(f.path))
        self.field_combo.blockSignals(True); self.field_combo.clear()
        for topic,spec in m["topics"].items():
            for field,desc in spec["fields"].items(): self.field_combo.addItem(f"{topic}.{field} [{desc['unit']}]")
        self.field_combo.blockSignals(False); self.change_domain(); self.plot_field(self.field_combo.currentText())
        self._update_scene_hint(); self._apply_camera_choice()
        self.welcome.hide(); self._set_controls_ready(not self.loading)
        if not self.loading: self.timer.start()

    def change_domain(self):
        if self.flight: self.view.set_flight(self.flight,self.domain.currentData()); self.seek()

    def plot_field(self,label):
        if not self.flight or not label: return
        key=label.split(" [",1)[0]; topic,field=key.split(".",1); spec=self.flight.manifest["topics"][topic]["fields"][field]
        self.plot.clear(); self.plot.addItem(self.cursor,ignoreBounds=True)
        for run_index,f in enumerate(self.flights):
            if topic not in f.topics or field not in f.topics[topic]: continue
            data=f.field(topic,field).reshape(len(f.time(topic)),-1)
            for i in range(data.shape[1]):
                color=QtGui.QColor(theme.method_color(f.manifest['method'])); color.setAlphaF(max(.45,1-i*.08))
                item=self.plot.plot(f.time(topic),data[:,i],pen=pg.mkPen(color,width=1.3),name=f"{f.manifest['method']} · s{f.manifest['seed']} [{i}]")
                item.setClipToView(True); item.setDownsampling(auto=True,method="peak")
                if not spec.get('allow_nan',False): item.setSkipFiniteCheck(True)
        self.plot.setLabel("bottom","mission time",units="s"); self.plot.setLabel("left",key,units=spec["unit"])
        self.plot.setTitle(f"{key} · {self.flight.manifest['topics'][topic]['domain']} · {self.flight.manifest['topics'][topic]['frame']}")

    def seek(self):
        if self.flight:
            t=self.slider.value()/10000*self.flight.manifest["duration_s"]; self._current_time=t
            self.time_label.setText(f"t = {t:.3f} / {self.flight.manifest['duration_s']:.1f} s")
            now=time.monotonic()
            if self.curve_drawer.isVisible() and (not self._advancing or now-self._last_curve_update>=1/30):
                self.cursor.setValue(t); self._last_curve_update=now
            if self.playing and not self._advancing: self.rebase_playback()
            self.view.set_time(t)

    def toggle_play(self):
        if self.flight is None or self.loading: return
        self.playing=not self.playing; self.clock=time.monotonic(); self.play.setIcon(icon('pause' if self.playing else 'play'))
        self.rebase_playback()

    def rebase_playback(self):
        self._play_wall=time.monotonic(); self._play_origin=self._current_time

    def advance(self):
        now=time.monotonic()
        if self.playing and self.flight:
            # 由绝对经过时间计算位置，避免每帧整数滑块取整累积造成慢放和抖动。
            rate=float(self.speed.currentText().rstrip("×")); value=round((self._play_origin+(now-self._play_wall)*rate)/self.flight.manifest["duration_s"]*10000)
            self._advancing=True
            try: self.slider.setValue(min(10000,value))
            finally: self._advancing=False
            if value>=10000: self.playing=False; self.play.setIcon(icon('play'))

    def export_png(self):
        if self.flight is None: return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,"导出当前视图","windtrace.png","PNG (*.png)")
        if path: self.screenshot(path)

    def screenshot(self,path):
        image=self.grab()
        # 离屏Qt的grab不一定包含OpenGL子窗口，显式合成VTK帧缓冲。
        if self.view.plotter is not None:
            pixels=np.ascontiguousarray(self.view.plotter.screenshot(return_img=True))
            fmt=QtGui.QImage.Format.Format_RGBA8888 if pixels.shape[2]==4 else QtGui.QImage.Format.Format_RGB888
            qimage=QtGui.QImage(pixels.data,pixels.shape[1],pixels.shape[0],pixels.strides[0],fmt).copy()
            painter=QtGui.QPainter(image); widget=self.view.surface
            position=widget.mapTo(self,QtCore.QPoint(0,0))
            painter.drawImage(QtCore.QRect(position,widget.size()),qimage)
            for overlay in [self.view.badge,self.rail,self.left_drawer,self.curve_drawer,self.welcome]:
                if overlay.isVisible(): painter.drawPixmap(overlay.mapTo(self,QtCore.QPoint(0,0)),overlay.grab())
            painter.end()
        return image.save(str(path))

    def closeEvent(self,event):
        self._closing=True; self.timer.stop(); self.load_poll.stop()
        if self._load_future is not None: self._load_future.cancel()
        if self._executor is not None: self._executor.shutdown(wait=False,cancel_futures=True)
        self.parameters_dialog.close(); self.source_dialog.close(); self.view.close(); super().closeEvent(event)
