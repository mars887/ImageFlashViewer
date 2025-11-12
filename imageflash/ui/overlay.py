from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QImage, QPixmap
from PySide6.QtWidgets import QWidget
from ..config import CONFIG

# Developer Notes (ui/overlay.py)
# - Fullscreen overlay for “spotlight” preview. Non-interactive; draws a dim
#   background and centers a scaled image with margins. Optional footer shows
#   relative path, file size and image dimensions.
# - Set via set_image() and set_footer(); the main window controls visibility.


class OverlayWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setVisible(False)
        self._footer: Optional[str] = None

    def set_image(self, image: Optional[QImage]) -> None:
        self._image = image
        self.update()

    def set_footer(self, text: Optional[str]) -> None:
        self._footer = text
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

        # Footer info bar
        if self._footer:
            fm = p.fontMetrics()
            pad_x = 12
            pad_y = 6
            bar_h = fm.height() + pad_y * 2
            rect = self.rect().adjusted(0, self.height() - bar_h, 0, 0)
            p.fillRect(rect, QColor(0, 0, 0, 180))
            p.setPen(QColor(235, 235, 235))
            text = fm.elidedText(self._footer, Qt.ElideMiddle, self.width() - pad_x * 2)
            p.drawText(rect.adjusted(pad_x, 0, -pad_x, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
