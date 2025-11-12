from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QImage, QPixmap
from PySide6.QtWidgets import QWidget
from ..config import CONFIG

# Developer Notes (ui/view_single.py)
# - Displays a single image scaled to fit, with optional bottom status stripe.
# - When a path text is provided (set_path_text), draws a bottom bar where ~90%
#   shows the elided relative path and ~10% indicates status color.
# - Emits requestRescale on resize so the main window can request a better-sized
#   image from the preloader.


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
        self._path_text: Optional[str] = None

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

    def set_path_text(self, text: Optional[str]) -> None:
        self._path_text = text
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

        # Status stripe (only when no path bar shown)
        if self._status != 0 and not self._path_text:
            stripe_h = CONFIG.single_status_stripe_height
            color = QColor(*CONFIG.stripe_positive_color) if self._status > 0 else QColor(*CONFIG.stripe_negative_color)
            painter.fillRect(0, self.height() - stripe_h, self.width(), stripe_h, color)

        # Path label when requested
        if self._path_text:
            fm = painter.fontMetrics()
            pad_x = 8
            pad_y = 3
            bar_h = fm.height() + pad_y * 2
            rect = self.rect().adjusted(0, self.height() - bar_h, 0, 0)
            painter.fillRect(rect, QColor(0, 0, 0, 150))
            # Status segment 10% width on the right
            seg_w = max(6, int(rect.width() * 0.10))
            if self._status != 0:
                base_col = QColor(*CONFIG.stripe_positive_color) if self._status > 0 else QColor(*CONFIG.stripe_negative_color)
                col = QColor(base_col.red(), base_col.green(), base_col.blue(), int(255 * 0.8))
                painter.fillRect(rect.right() - seg_w + 1, rect.y(), seg_w, rect.height(), col)
            # Path text on remaining ~90%
            text_width = rect.width() - pad_x * 2 - seg_w
            text = fm.elidedText(self._path_text, Qt.ElideMiddle, max(10, text_width))
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(rect.adjusted(pad_x, 0, -pad_x - seg_w, 0), Qt.AlignVCenter | Qt.AlignLeft, text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        # Request a better sized image
        self._scaled_pixmap = None
        self._scaled_for = None
        self.requestRescale.emit()
        super().resizeEvent(event)
