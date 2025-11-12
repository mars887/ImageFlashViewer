from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QTimer
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
    openExternalRequested = Signal(int)  # global_index
    contextMenuRequested = Signal(int, QPoint)  # global_index, global position

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
        self._show_info_res: bool = False
        self._show_info_size: bool = False
        self._show_info_fmt: bool = False

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

    def set_show_info_res(self, show: bool) -> None:
        if self._show_info_res != show:
            self._show_info_res = show
            self.update()

    def set_show_info_size(self, show: bool) -> None:
        if self._show_info_size != show:
            self._show_info_size = show
            self.update()

    def set_show_info_fmt(self, show: bool) -> None:
        if self._show_info_fmt != show:
            self._show_info_fmt = show
            self.update()

    def _format_mp(self, w: int, h: int) -> str:
        mp = (w * h) / 1_000_000.0
        s = f"{mp:.2f}".rstrip('0').rstrip('.')
        return f"{s}M"

    def _badge_color(self, w: int, h: int) -> QColor:
        """Pick color using CONFIG.resolution_badges thresholds.
        Compute ranks separately for megapixels (mp) and min side (ms), then
        choose the worse (minimum) rank. The first/highest rule uses strict
        '>' comparison; others use '>=' to match the examples.
        """
        mp = (w * h) / 1_000_000.0
        ms = min(w, h)
        rules = CONFIG.resolution_badges

        def find_index(value, is_mp: bool) -> int:
            # Return 0-based index in rules where value meets threshold.
            for i, (mp_thr, ms_thr, _color) in enumerate(rules):
                thr = mp_thr if is_mp else ms_thr
                if i == 0:
                    # top tier: strict greater than
                    if value > thr:
                        return i
                else:
                    if value >= thr:
                        return i
            return len(rules) - 1

        i_mp = find_index(mp, True)
        i_ms = find_index(ms, False)

        # Convert indices (0=best ... n-1=worst) to ranks (1=worst ... n=best)
        n = len(rules)
        rank_mp = n - i_mp
        rank_ms = n - i_ms
        final_rank = min(rank_mp, rank_ms)
        idx = n - final_rank  # back to 0-based rule index

        _, _, hex_color = rules[idx]
        c = QColor(hex_color)
        c.setAlpha(CONFIG.resolution_badge_alpha)
        return c

    def _size_badge_color(self, kb: int) -> QColor:
        """Pick color for file size badge using CONFIG.size_badges.
        Rules are ordered from high to low; top rule uses strict '>' and others
        use '>=' to mirror resolution logic.
        """
        rules = CONFIG.size_badges
        idx = len(rules) - 1
        for i, (thr_kb, hex_color) in enumerate(rules):
            if i == 0:
                if kb > thr_kb:
                    idx = i
                    break
            else:
                if kb >= thr_kb:
                    idx = i
                    break
        hex_color = rules[idx][1]
        c = QColor(hex_color)
        c.setAlpha(CONFIG.resolution_badge_alpha)
        return c

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
        # If tiles are not laid out yet (very small), defer loading until after layout
        if tw < 8 or th < 8:
            QTimer.singleShot(0, self.requestRescale.emit)
            return
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
                        # Always scale to current tile size to avoid undersized/oversized cached images
                        pm = QPixmap.fromImage(img).scaled(
                            rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        # center inside rect
                        x = rect.x() + (rect.width() - pm.width()) // 2
                        y = rect.y() + (rect.height() - pm.height()) // 2
                        # Clip drawing to tile rect to avoid bleed
                        p.save()
                        p.setClipRect(rect)
                        p.drawPixmap(x, y, pm)
                        p.restore()
                    # Status stripe (only when not showing path bar)
                    st = int(item.get("status", 0))
                    if st != 0 and not self._show_paths:
                        stripe_h = CONFIG.grid_status_stripe_height
                        color = QColor(*CONFIG.stripe_positive_color) if st > 0 else QColor(*CONFIG.stripe_negative_color)
                        p.fillRect(rect.x(), rect.y() + rect.height() - stripe_h, rect.width(), stripe_h, color)
                # Border
                p.setPen(QColor(*CONFIG.border_color))
                p.drawRect(rect)
                # Info badges (top-right): order right->left: Res, Size, Fmt
                fm = self.fontMetrics()
                pad_x, pad_y = 6, 2
                gap = 4
                cursor_x = rect.right() - 6
                top_y = rect.y() + 6
                if i < len(self._items):
                    it = self._items[i]
                    # Res
                    if self._show_info_res:
                        w = it.get("w")
                        h = it.get("h")
                        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                            text = self._format_mp(w, h)
                            tw = fm.horizontalAdvance(text) + pad_x * 2
                            th = fm.height() + pad_y * 2
                            badge = QRect(cursor_x - tw, top_y, tw, th)
                            color = self._badge_color(w, h)
                            p.fillRect(badge, color)
                            p.setPen(QColor(0, 0, 0, 180))
                            p.drawRect(badge)
                            p.setPen(QColor(20, 20, 20))
                            p.drawText(badge, Qt.AlignCenter, text)
                            cursor_x = badge.left() - gap
                    # Size
                    if self._show_info_size:
                        kb = it.get("size_kb")
                        if isinstance(kb, int) and kb >= 0:
                            text = f"{kb}KБ"
                            tw = fm.horizontalAdvance(text) + pad_x * 2
                            th = fm.height() + pad_y * 2
                            badge = QRect(cursor_x - tw, top_y, tw, th)
                            color = self._size_badge_color(kb)
                            p.fillRect(badge, color)
                            p.setPen(QColor(0, 0, 0, 180))
                            p.drawRect(badge)
                            p.setPen(QColor(20, 20, 20))
                            p.drawText(badge, Qt.AlignCenter, text)
                            cursor_x = badge.left() - gap
                    # Fmt
                    if self._show_info_fmt:
                        fmt = it.get("fmt")
                        if isinstance(fmt, str) and fmt:
                            text = fmt
                            tw = fm.horizontalAdvance(text) + pad_x * 2
                            th = fm.height() + pad_y * 2
                            badge = QRect(cursor_x - tw, top_y, tw, th)
                            color = QColor(CONFIG.format_badge_color)
                            color.setAlpha(CONFIG.resolution_badge_alpha)
                            p.fillRect(badge, color)
                            p.setPen(QColor(0, 0, 0, 180))
                            p.drawRect(badge)
                            p.setPen(QColor(20, 20, 20))
                            p.drawText(badge, Qt.AlignCenter, text)
                            cursor_x = badge.left() - gap
                i += 1

        # Overlay page badge (compact): "start–end of total | page of pages"
        if self._page_info:
            start, end, total = self._page_info
            page_size = max(1, self._rows * self._cols)
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0
            current_page = ((start - 1) // page_size) + 1 if total > 0 else 0
            text = f"{start}\u2013{end} of {total} | {current_page} of {total_pages}"
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
                        elif event.button() == Qt.MiddleButton:
                            if event.modifiers() & Qt.ShiftModifier:
                                self.openExternalRequested.emit(int(item.get("index")))
                            else:
                                self.contextMenuRequested.emit(int(item.get("index")), event.globalPosition().toPoint())
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
