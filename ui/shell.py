"""沿用WindTrace原版视觉组件与设计令牌；来源见IMPORT_PROVENANCE.json。"""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ui import theme
from ui.icons import icon

ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"
LOGO_256 = ASSET_ROOT / "logo_256.png"
LOGO_64 = ASSET_ROOT / "logo_64.png"


class Breadcrumb(QtWidgets.QWidget):
    """沿用WindTrace原版视觉组件与设计令牌；来源见IMPORT_PROVENANCE.json。"""

    segmentClicked = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("breadcrumb")
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(theme.SPACING["xxs"])
        self._buttons: list[QtWidgets.QToolButton] = []
        self._separators: list[QtWidgets.QLabel] = []
        for index in range(4):
            btn = QtWidgets.QToolButton(self)
            btn.setObjectName("crumb")
            btn.setAutoRaise(True)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=index: self.segmentClicked.emit(i))
            self._layout.addWidget(btn)
            self._buttons.append(btn)
            if index < 3:
                sep = QtWidgets.QLabel("›", self)
                sep.setObjectName("crumbSep")
                self._layout.addWidget(sep)
                self._separators.append(sep)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum, QtWidgets.QSizePolicy.Policy.Fixed)

    def set_segments(self, texts: list[str] | tuple[str, ...]) -> None:
        for btn, text in zip(self._buttons, texts):
            btn.setText(str(text))
            btn.adjustSize()

    def button(self, index: int) -> QtWidgets.QToolButton:
        return self._buttons[index]

    def set_path_tooltip(self, path: str) -> None:
        tip = path
        for btn in self._buttons:
            btn.setToolTip(tip)


class SideRail(QtWidgets.QFrame):
    """沿用WindTrace原版视觉组件与设计令牌；来源见IMPORT_PROVENANCE.json。"""

    sectionClicked = QtCore.Signal(str)
    closeClicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("leftRail")
        self.setFixedWidth(36)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 6)
        layout.setSpacing(4)
        self._buttons: dict[str, QtWidgets.QToolButton] = {}
        for key, glyph, tip in (("data", "☰", "参数"),):
            btn = QtWidgets.QToolButton(self)
            btn.setObjectName("railButton")
            btn.setText(glyph)
            btn.setToolTip(tip)
            btn.setFixedSize(32, 32)
            btn.clicked.connect(lambda _checked=False, k=key: self.sectionClicked.emit(k))
            layout.addWidget(btn, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)
            self._buttons[key] = btn
        layout.addStretch(1)
        self.btn_close = QtWidgets.QToolButton(self)
        self.btn_close.setObjectName("railButton")
        self.btn_close.setText("«")
        self.btn_close.setToolTip("收起抽屉（Tab / Esc）")
        self.btn_close.setFixedSize(32, 32)
        self.btn_close.clicked.connect(self.closeClicked)
        layout.addWidget(self.btn_close, alignment=QtCore.Qt.AlignmentFlag.AlignHCenter)

    def set_active(self, key: str | None) -> None:
        for k, btn in self._buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)


class AccordionSection(QtWidgets.QWidget):
    """沿用WindTrace原版视觉组件与设计令牌；来源见IMPORT_PROVENANCE.json。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QtWidgets.QToolButton(self)
        self.header.setObjectName("accordionHeader")
        self.header.setCheckable(True)
        self.header.setChecked(False)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setIconSize(QtCore.QSize(14, 14))
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.header.setFixedHeight(34)
        self.header.clicked.connect(self._toggle)
        outer.addWidget(self.header)
        self.content = QtWidgets.QWidget(self)
        self.content.setObjectName("accordionContent")
        self.content_layout = QtWidgets.QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 4, 0, 12)
        self.content_layout.setSpacing(theme.SPACING["xs"])
        self.content.setVisible(False)
        outer.addWidget(self.content)
        self._render()

    def _render(self) -> None:
        self.header.setIcon(icon("down" if self.header.isChecked() else "right"))
        self.header.setText(self._title)

    def _toggle(self) -> None:
        self.set_expanded(self.header.isChecked())

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(bool(expanded))
        self.content.setVisible(bool(expanded))
        self._render()


class AboutDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于 风迹 WindTrace")
        self.setModal(True)
        self.setFixedWidth(430)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACING["lg"], theme.SPACING["lg"], theme.SPACING["lg"], theme.SPACING["lg"])
        layout.setSpacing(theme.SPACING["sm"])
        logo = QtWidgets.QLabel(self)
        pix = QtGui.QPixmap(str(LOGO_256))
        if not pix.isNull():
            logo.setPixmap(pix.scaled(96, 96, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(logo)
        title = QtWidgets.QLabel("风迹 WindTrace", self)
        title.setObjectName("aboutTitle")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)
        version = QtWidgets.QLabel(f"v{theme.APP_VERSION}", self)
        version.setProperty("muted", True)
        version.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version)
        source = QtWidgets.QLabel("数据来源：SHC09 飞行日志 · 后处理回放", self)
        source.setWordWrap(True)
        source.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(source)
        display = QtWidgets.QLabel("显示约定：示意模型按几何底点贴地，抬升量随日志几何计算，只影响画面，不改变日志位置或指标。", self)
        display.setProperty("muted", True)
        display.setWordWrap(True)
        display.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(display)
        camera = QtWidgets.QLabel("相机：跟随／自由／追尾／环绕／总览／机体特写，可导入运镜脚本；相机不参与控制或评价。", self)
        camera.setProperty("muted", True)
        camera.setWordWrap(True)
        camera.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(camera)
        note = QtWidgets.QLabel("replay only, not a ranking", self)
        note.setObjectName("aboutNote")
        note.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
