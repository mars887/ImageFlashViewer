from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QImage, QPixmap
from PySide6.QtWidgets import QWidget
from ..config import CONFIG


class OverlayWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setVisible(False)

    def set_image(self, image: Optional[QImage]) -> None:
        self._image = image
        self.update()

    def viewport_size(self) -> Tuple[int, int]:
        margin = getattr(CONFIG, 'overlay_margin', 32)
        return max(1, self.width() - 2 * margin), max(1, self.height() - 2 * margin)

    def show_overlay(self) -> None:
        self.setVisible(True)
        self.raise_()

    def hide_overlay(self) -> None:
        self.setVisible(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.isVisible():
            return
        p = QPainter(self)
        alpha = getattr(CONFIG, 'overlay_bg_alpha', 180)
        p.fillRect(self.rect(), QColor(0, 0, 0, alpha))

        if self._image is None or self._image.isNull():
            return
        margin = getattr(CONFIG, 'overlay_margin', 32)
        avail_w = max(1, self.width() - 2 * margin)
        avail_h = max(1, self.height() - 2 * margin)
        scaled = self._image.scaled(avail_w, avail_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm = QPixmap.fromImage(scaled)
        x = (self.width() - pm.width()) // 2
        y = (self.height() - pm.height()) // 2
        p.drawPixmap(x, y, pm)

