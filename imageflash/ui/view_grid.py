from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QColor, QImage, QPixmap, QMouseEvent
from PySide6.QtWidgets import QWidget
from ..config import CONFIG

# Developer Notes (ui/view_grid.py)
# - Renders a grid of tiles (rows x cols) and requests tile-sized images via
#   a preloader callback. Each tile can show a status stripe or a bottom path
#   bar with an embedded status segment.
# - Emits cellMarkRequested(global_index, new_status) when tiles are clicked.
#   index_at_point(pt) maps mouse position to a global index.
# - A compact page badge (start–end of total) is drawn in the top-left.


class ViewGridWidget(QWidget):
    requestRescale = Signal()
    cellMarkRequested = Signal(int, int)  # global_index, new_status

    def __init__(self) -> None:
        super().__init__()
        self._rows = 1
        self._cols = 1
        self._items: List[Dict] = []  # each: {index:int, path:str, status:int}
        self._images: Dict[int, QImage] = {}  # key: global index
        self._request_image = None  # callable(path, (w,h), callback)
        self._page_info: Optional[Tuple[int, int, int]] = None  # start,end,total
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self._show_paths: bool = False

    def set_request_image(self, fn) -> None:
        self._request_image = fn

    def set_grid_size(self, cols: int, rows: int) -> None:
        cols = max(1, min(3, cols))
        rows = max(1, min(3, rows))
        if cols == self._cols and rows == self._rows:
            return
        self._cols = cols
        self._rows = rows
        self._images.clear()
        self.requestRescale.emit()
        self.update()

    def grid_size(self) -> Tuple[int, int]:
        return self._cols, self._rows

    def viewport_tile_size(self) -> Tuple[int, int]:
        # Padding between tiles
        spacing = CONFIG.grid_tile_spacing
        w = max(1, (self.width() - (self._cols + 1) * spacing) // self._cols)
        h = max(1, (self.height() - (self._rows + 1) * spacing) // self._rows)
        return w, h

    def _tile_rect(self, r: int, c: int) -> QRect:
        spacing = CONFIG.grid_tile_spacing
        tw, th = self.viewport_tile_size()
        x = spacing + c * (tw + spacing)
        y = spacing + r * (th + spacing)
        return QRect(x, y, tw, th)

    def set_items(self, items: List[Dict]) -> None:
        # items: [{index:int, path:str, status:int}]
        self._items = items
        self._images.clear()
        self._load_visible_images()
        self.update()

    def set_page_info(self, start: int, end: int, total: int) -> None:
        self._page_info = (start, end, total)
        self.update()

    def set_show_paths(self, show: bool) -> None:
        if self._show_paths != show:
            self._show_paths = show
            self.update()

    def update_item_status(self, global_index: int, status: int) -> None:
        for it in self._items:
            if it.get("index") == global_index:
                it["status"] = status
                break
        self.update()

    def _load_visible_images(self) -> None:
        if not self._request_image:
            return
        tw, th = self.viewport_tile_size()
        for it in self._items:
            idx = it.get("index")
            path = it.get("path")
            if idx is None or not path:
                continue
            def make_cb(i: int):
                def _cb(img: QImage):
                    self._images[i] = img
                    self.update()
                return _cb
            self._request_image(path, (tw, th), make_cb(idx))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(*CONFIG.background_color))

        # Draw tiles
        i = 0
        for rr in range(self._rows):
            for cc in range(self._cols):
                rect = self._tile_rect(rr, cc)
                # Draw background for tile
                p.fillRect(rect, QColor(*CONFIG.tile_background_color))
                if i < len(self._items):
                    item = self._items[i]
                    img = self._images.get(item.get("index", -1))
                    if img is not None and not img.isNull():
                        scaled = img  # already scaled by preloader request
                        pm = QPixmap.fromImage(scaled)
                        # center inside rect
                        x = rect.x() + (rect.width() - pm.width()) // 2
                        y = rect.y() + (rect.height() - pm.height()) // 2
                        p.drawPixmap(x, y, pm)
                    # Status stripe (only when not showing path bar)
                    st = int(item.get("status", 0))
                    if st != 0 and not self._show_paths:
                        stripe_h = CONFIG.grid_status_stripe_height
                        color = QColor(*CONFIG.stripe_positive_color) if st > 0 else QColor(*CONFIG.stripe_negative_color)
                        p.fillRect(rect.x(), rect.y() + rect.height() - stripe_h, rect.width(), stripe_h, color)
                # Border
                p.setPen(QColor(*CONFIG.border_color))
                p.drawRect(rect)
                i += 1

        # Overlay page badge (compact): "start–end of total"
        if self._page_info:
            start, end, total = self._page_info
            text = f"{start}\u2013{end} of {total}"
            metrics_padding = 6
            fm = self.fontMetrics()
            tw = fm.horizontalAdvance(text) + metrics_padding * 2
            th = fm.height() + metrics_padding
            rect = QRect(8, 8, tw, th)
            # Badge background with semi-transparency
            p.fillRect(rect, QColor(0, 0, 0, 140))
            p.setPen(QColor(230, 230, 230))
            p.drawText(rect.adjusted(metrics_padding, 0, -metrics_padding, 0), Qt.AlignVCenter | Qt.AlignLeft, text)

        # If showing paths, draw under each tile
        if self._show_paths:
            i = 0
            fm = self.fontMetrics()
            pad_x = 6
            pad_y = 2
            for rr in range(self._rows):
                for cc in range(self._cols):
                    if i < len(self._items):
                        item = self._items[i]
                        rect = self._tile_rect(rr, cc)
                        # Background bar
                        bar_h = fm.height() + pad_y * 2
                        bar_rect = QRect(rect.x(), rect.y() + rect.height() - bar_h, rect.width(), bar_h)
                        p.fillRect(bar_rect, QColor(0, 0, 0, 150))
                        # Status segment (10% width of bar)
                        st = int(item.get("status", 0))
                        if st != 0:
                            seg_w = max(6, int(bar_rect.width() * 0.20))
                            seg_rect = QRect(bar_rect.right() - seg_w + 1, bar_rect.y(), seg_w, bar_rect.height())
                            base_col = QColor(*CONFIG.stripe_positive_color) if st > 0 else QColor(*CONFIG.stripe_negative_color)
                            col = QColor(base_col.red(), base_col.green(), base_col.blue(), int(255 * 0.8))
                            p.fillRect(seg_rect, col)
                        # Text: relative path occupying ~90%
                        text_width = bar_rect.width() - pad_x * 2 - max(0, int(bar_rect.width() * 0.20))
                        rel = item.get("rel") or item.get("path", "")
                        text = fm.elidedText(rel, Qt.ElideMiddle, max(10, text_width))
                        p.setPen(QColor(235, 235, 235))
                        p.drawText(bar_rect.adjusted(pad_x, 0, -pad_x - max(0, int(bar_rect.width() * 0.20)), 0), Qt.AlignVCenter | Qt.AlignLeft, text)
                    i += 1

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.requestRescale.emit()
        self._images.clear()
        self._load_visible_images()
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        # Find tile
        i = 0
        for rr in range(self._rows):
            for cc in range(self._cols):
                rect = self._tile_rect(rr, cc)
                if rect.contains(pos):
                    if i < len(self._items):
                        item = self._items[i]
                        cur = int(item.get("status", 0))
                        if event.button() == Qt.LeftButton:
                            new_status = 0 if cur == 1 else 1
                            self.cellMarkRequested.emit(int(item.get("index")), new_status)
                        elif event.button() == Qt.RightButton:
                            new_status = 0 if cur == -1 else -1
                            self.cellMarkRequested.emit(int(item.get("index")), new_status)
                    return
                i += 1
        super().mousePressEvent(event)

    def index_at_point(self, pt) -> Optional[int]:
        # Returns global index for cell under point, or None
        i = 0
        for rr in range(self._rows):
            for cc in range(self._cols):
                if i < len(self._items):
                    rect = self._tile_rect(rr, cc)
                    if rect.contains(pt):
                        item = self._items[i]
                        return int(item.get("index"))
                i += 1
        return None
