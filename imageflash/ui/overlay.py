from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton, QWidget

from ..config import CONFIG

# Developer Notes (ui/overlay.py)
# - Fullscreen spotlight overlay with two modes:
#   * preview mode: follows the current image under the cursor and ignores mouse
#   * locked mode: keeps the current image pinned, enables zoom/pan and shows
#     action buttons in the lower-left corner
# - Footer text is multi-line and rendered inside a bottom information panel.


class OverlayWidget(QWidget):
    copyRequested = Signal()
    externalRequested = Signal()
    folderRequested = Signal()
    replaceRequested = Signal()
    statusRequested = Signal()
    unlockRequested = Signal()
    requestImageRefresh = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._pixmap: Optional[QPixmap] = None
        self._footer: Optional[str] = None
        self._status: Optional[int] = None
        self._locked: bool = False
        self._zoom: float = 1.0
        self._pan = QPoint(0, 0)
        self._dragging = False
        self._drag_last_pos = QPoint()
        self._image_rect = QRect()
        self._button_style = """
            QPushButton {
                min-height: 24px;
                padding: 4px 4px;
                border-radius: 6px;
                color: #f4f4f4;
                background: rgba(36, 36, 36, 220);
                border: 1px solid rgba(220, 220, 220, 50);
            }
            QPushButton:hover {
                background: rgba(58, 58, 58, 235);
            }
        """

        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setMouseTracking(True)
        self.setVisible(False)

        self.btn_copy = QPushButton("Copy", self)
        self.btn_external = QPushButton("External", self)
        self.btn_folder = QPushButton("Folder", self)
        self.btn_replace = QPushButton("Replace", self)
        self.btn_status = QPushButton("Status", self)
        self._buttons = [
            self.btn_copy,
            self.btn_external,
            self.btn_folder,
            self.btn_replace,
            self.btn_status,
        ]
        for button in self._buttons:
            button.hide()
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(self._button_style)

        self.btn_copy.clicked.connect(self.copyRequested.emit)
        self.btn_external.clicked.connect(self.externalRequested.emit)
        self.btn_folder.clicked.connect(self.folderRequested.emit)
        self.btn_replace.clicked.connect(self.replaceRequested.emit)
        self.btn_status.clicked.connect(self.statusRequested.emit)

    def _image_area_rect(self) -> QRect:
        margin = getattr(CONFIG, "overlay_margin", 32)
        footer_h = self._footer_panel_height()
        image_area = self.rect().adjusted(margin, margin, -margin, -margin)
        if image_area.height() < 1:
            image_area = self.rect().adjusted(margin, margin, -margin, -margin)
        return image_area

    def _draw_rect_for(self, zoom: Optional[float] = None, pan: Optional[QPoint] = None) -> QRect:
        if self._pixmap is None or self._pixmap.isNull():
            return QRect()
        image_area = self._image_area_rect()
        fit_size = self._pixmap.size()
        fit_size.scale(image_area.size(), Qt.KeepAspectRatio)
        zoom = self._zoom if zoom is None else zoom
        pan = self._pan if pan is None else pan
        draw_w = max(1, int(fit_size.width() * zoom))
        draw_h = max(1, int(fit_size.height() * zoom))
        x = image_area.x() + (image_area.width() - draw_w) // 2 + pan.x()
        y = image_area.y() + (image_area.height() - draw_h) // 2 + pan.y()
        return QRect(x, y, draw_w, draw_h)

    def set_image(self, image: Optional[QImage]) -> None:
        self._image = image
        self._pixmap = QPixmap.fromImage(image) if image is not None and not image.isNull() else None
        self.update()

    def set_footer(self, text: Optional[str]) -> None:
        self._footer = text
        self._layout_controls()
        self.update()

    def set_status(self, status: Optional[int]) -> None:
        self._status = status
        self._apply_status_style()

    def set_locked(self, locked: bool) -> None:
        locked = bool(locked)
        if self._locked == locked:
            return
        self._locked = locked
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not locked)
        if not locked:
            self._dragging = False
            self._zoom = 1.0
            self._pan = QPoint(0, 0)
        self._layout_controls()
        self.update()

    def is_locked(self) -> bool:
        return self._locked

    def viewport_size(self) -> Tuple[int, int]:
        margin = getattr(CONFIG, "overlay_margin", 32)
        footer_h = self._footer_panel_height()
        return (
            max(1, self.width() - 2 * margin),
            max(1, self.height() - 2 * margin - footer_h),
        )

    def requested_image_size(self) -> Tuple[int, int]:
        base_w, base_h = self.viewport_size()
        if not self._locked:
            return base_w, base_h
        return max(1, int(base_w * self._zoom)), max(1, int(base_h * self._zoom))

    def show_overlay(self) -> None:
        self.setVisible(True)
        self.raise_()
        self._layout_controls()

    def hide_overlay(self) -> None:
        self.setVisible(False)
        self._dragging = False
        self._layout_controls()

    def _footer_lines(self) -> list[str]:
        if not self._footer:
            return []
        return [line for line in self._footer.splitlines() if line.strip()]

    def _footer_panel_height(self) -> int:
        if not self._footer and not self._locked:
            return 0
        fm = self.fontMetrics()
        lines = max(1, len(self._footer_lines()))
        line_h = fm.height() + 10
        text_h = lines * line_h + max(0, lines - 1) * 6
        controls_h = 36 if self._locked else 0
        return text_h + controls_h

    def _layout_controls(self) -> None:
        visible = self.isVisible() and self._locked
        for button in self._buttons:
            button.setVisible(visible)
        if not visible:
            return

        spacing = 8
        x = 12
        button_h = 31
        y = self.height() - 8 - button_h
        for button in self._buttons:
            width = max(72, button.sizeHint().width())
            button.setGeometry(x, y, width, button_h)
            x += width + spacing

    def _apply_status_style(self) -> None:
        if self._status is None:
            self.btn_status.setText("Status")
            self.btn_status.setStyleSheet(self._button_style)
            return

        if self._status > 0:
            color = "#2f8f46"
        elif self._status < 0:
            color = "#b33a3a"
        else:
            color = "#6a6a6a"

        self.btn_status.setText("Status")
        self.btn_status.setStyleSheet(
            f"""
            QPushButton {{
                min-height: 24px;
                padding: 4px 4px;
                border-radius: 6px;
                color: #f4f4f4;
                background: {color};
                border: 1px solid rgba(255, 255, 255, 45);
            }}
            QPushButton:hover {{
                background: {color};
                border: 1px solid rgba(255, 255, 255, 80);
            }}
            """
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._layout_controls()
        super().resizeEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if not self._locked or self._pixmap is None or self._pixmap.isNull():
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.accept()
            return
        old_rect = self._draw_rect_for()
        cursor_pos = event.position().toPoint()
        if old_rect.width() > 0 and old_rect.height() > 0:
            rel_x = (cursor_pos.x() - old_rect.x()) / max(1, old_rect.width())
            rel_y = (cursor_pos.y() - old_rect.y()) / max(1, old_rect.height())
        else:
            rel_x = 0.5
            rel_y = 0.5
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        new_zoom = max(1.0, min(8.0, self._zoom * factor))
        base_rect = self._draw_rect_for(zoom=new_zoom, pan=QPoint(0, 0))
        if base_rect.width() > 0 and base_rect.height() > 0:
            new_pan_x = cursor_pos.x() - (base_rect.x() + rel_x * base_rect.width())
            new_pan_y = cursor_pos.y() - (base_rect.y() + rel_y * base_rect.height())
            self._pan = QPoint(int(round(new_pan_x)), int(round(new_pan_y)))
        self._zoom = new_zoom
        self.requestImageRefresh.emit()
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._locked and event.button() == Qt.RightButton:
            self.unlockRequested.emit()
            event.accept()
            return
        if (
            self._locked
            and event.button() == Qt.LeftButton
            and not any(button.geometry().contains(event.position().toPoint()) for button in self._buttons if button.isVisible())
        ):
            self._dragging = True
            self._drag_last_pos = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._locked and self._dragging:
            pos = event.position().toPoint()
            delta = pos - self._drag_last_pos
            self._drag_last_pos = pos
            self._pan += delta
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self.isVisible():
            return
        p = QPainter(self)
        alpha = getattr(CONFIG, "overlay_bg_alpha", 180)
        p.fillRect(self.rect(), QColor(0, 0, 0, alpha))

        footer_h = self._footer_panel_height()
        image_area = self._image_area_rect()

        self._image_rect = QRect()
        if self._pixmap is not None and not self._pixmap.isNull():
            self._image_rect = self._draw_rect_for()
            draw_pm = self._pixmap.scaled(
                self._image_rect.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            p.save()
            p.setClipRect(image_area)
            p.drawPixmap(self._image_rect.topLeft(), draw_pm)
            p.restore()

        if footer_h > 0:
            lines = self._footer_lines()
            if lines:
                fm = self.fontMetrics()
                p.setPen(QColor(235, 235, 235))
                pad_x = 3
                pad_y = 3
                gap_y = 5
                max_text_w = max(80, self.width() - 24)
                y = self.height() - footer_h + 6
                for line in lines:
                    text = fm.elidedText(line, Qt.ElideMiddle, max_text_w - pad_x * 2)
                    pill_w = min(max_text_w, fm.horizontalAdvance(text) + pad_x * 2)
                    pill_h = fm.height() + pad_y * 2
                    pill = QRect(12, y, pill_w, pill_h)
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, 190))
                    p.drawRoundedRect(pill, 5, 5)
                    p.setPen(QColor(235, 235, 235))
                    p.drawText(pill.adjusted(pad_x, 0, -pad_x, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
                    y += pill_h + gap_y
