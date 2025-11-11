from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QImage, QPixmap
from PySide6.QtWidgets import QWidget
from ..config import CONFIG


class ViewSingleWidget(QWidget):
    # Signal to request a better sized image when viewport changes
    requestRescale = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._image: Optional[QImage] = None
        self._scaled_pixmap: Optional[QPixmap] = None
        self._scaled_for: Optional[Tuple[int, int]] = None
        self._status: int = 0  # -1, 0, +1
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)

    def viewport_size(self) -> Tuple[int, int]:
        sz = self.size()
        return sz.width(), sz.height()

    def set_status(self, status: int) -> None:
        self._status = status
        self.update()

    def set_image(self, image: Optional[QImage]) -> None:
        self._image = image
        self._scaled_pixmap = None
        self._scaled_for = None
        self.update()

    def _ensure_scaled(self) -> None:
        if self._image is None:
            self._scaled_pixmap = None
            self._scaled_for = None
            return
        w, h = self.viewport_size()
        if w <= 0 or h <= 0:
            return
        if self._scaled_pixmap is not None and self._scaled_for == (w, h):
            return
        # Keep aspect ratio; smooth scaling
        scaled = self._image.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._scaled_pixmap = QPixmap.fromImage(scaled)
        self._scaled_for = (w, h)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        # Fill background
        bg = QColor(*CONFIG.background_color)
        painter.fillRect(self.rect(), bg)

        if self._image is not None:
            self._ensure_scaled()
            if self._scaled_pixmap is not None:
                pm = self._scaled_pixmap
                x = (self.width() - pm.width()) // 2
                y = (self.height() - pm.height()) // 2
                painter.drawPixmap(x, y, pm)

        # Status stripe (10px) at bottom, semi-transparent
        if self._status != 0:
            stripe_h = CONFIG.single_status_stripe_height
            color = QColor(*CONFIG.stripe_positive_color) if self._status > 0 else QColor(*CONFIG.stripe_negative_color)
            painter.fillRect(0, self.height() - stripe_h, self.width(), stripe_h, color)

    def resizeEvent(self, event) -> None:  # noqa: N802
        # Request a better sized image
        self._scaled_pixmap = None
        self._scaled_for = None
        self.requestRescale.emit()
        super().resizeEvent(event)
