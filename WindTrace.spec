# 打包窗口版单目录应用：依赖与资源随程序分发，从任意工作目录启动都能找到资源。
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH)
datas = [
    (str(root / 'assets'), 'assets'),
    (str(root / 'ui' / 'theme.qss'), 'ui'),
    (str(root / 'ui' / 'assets'), 'ui/assets'),
    (str(root / 'LICENSE'), '.'),
    (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
]
binaries = []
hiddenimports = []
for package in ['pyvista', 'pyvistaqt', 'pyqtgraph', 'vtkmodules']:
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += imports

a = Analysis([str(root / 'app.py')], pathex=[str(root)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PyQt5', 'PyQt6', 'PySide2', 'tkinter', 'pytest', 'notebook', 'jupyterlab'],
             noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='WindTrace', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, icon=[str(root / 'assets' / 'logo.ico')])
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='WindTrace')
