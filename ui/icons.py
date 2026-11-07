"""用矢量图标避免离屏字体缺少播放／折叠符号，沿用原版中性配色。"""
from PySide6 import QtCore,QtGui
from PySide6.QtSvg import QSvgRenderer


def icon(name):
    paths={
        'menu':'<path d="M4 6h16M4 12h16M4 18h16"/>',
        'play':'<path d="M8 5l11 7-11 7z" fill="#4B5563" stroke="none"/>',
        'pause':'<path d="M8 5v14M16 5v14" stroke-width="3"/>',
        'reset':'<path d="M5 8a8 8 0 1 1-1 8M5 3v6h6"/>',
        'up':'<path d="M6 15l6-6 6 6"/>',
        'down':'<path d="M6 9l6 6 6-6"/>',
        'right':'<path d="M9 6l6 6-6 6"/>',
        'download':'<path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 19h14"/>'}
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="#4B5563" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</g></svg>'
    pixmap=QtGui.QPixmap(24,24); pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter=QtGui.QPainter(pixmap); QSvgRenderer(svg.encode()).render(painter); painter.end()
    return QtGui.QIcon(pixmap)
