from __future__ import annotations

from itertools import product
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
    openExternalRequested = Signal(int)  # global_index
    contextMenuRequested = Signal(int, QPoint)  # global_index, global position

    def __init__(self) -> None:
        super().__init__()
        self._rows = 1
        self._cols = 1
        self._items: List[Dict] = []  # each: {index:int, path:str, status:int}
        self._images: Dict[int, QPixmap] = {}  # key: global index
        self._request_image = None  # callable(path, (w,h), callback)
        self._page_info: Optional[Tuple[int, int, int]] = None  # start,end,total
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self._show_paths: bool = False
        self._show_info_res: bool = False
        self._show_info_size: bool = False
        self._show_info_fmt: bool = False
        self._auto_balance: bool = bool(CONFIG.grid_auto_balance)
        self._auto_balance_only_grow: bool = bool(CONFIG.grid_auto_balance_only_grow)
        self._cached_col_widths: Optional[List[int]] = None
        self._cached_row_heights: Optional[List[int]] = None
        self._expected_image_requests: Dict[int, Tuple[int, str, Tuple[int, int]]] = {}
        self._image_request_serial: int = 0
        self._drag_button = Qt.NoButton
        self._drag_from_status: Optional[int] = None
        self._drag_to_status: Optional[int] = None
        self._drag_seen: set[int] = set()

    def set_request_image(self, fn) -> None:
        self._request_image = fn

    def set_grid_size(self, cols: int, rows: int) -> None:
        cols = max(CONFIG.grid_min_dimension, min(CONFIG.grid_max_dimension, cols))
        rows = max(CONFIG.grid_min_dimension, min(CONFIG.grid_max_dimension, rows))
        if cols == self._cols and rows == self._rows:
            return
        self._cols = cols
        self._rows = rows
        self._invalidate_layout_cache()
        self._images.clear()
        self._expected_image_requests.clear()
        self.requestRescale.emit()
        self.update()

    def grid_size(self) -> Tuple[int, int]:
        return self._cols, self._rows

    def set_auto_balance(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._auto_balance == enabled:
            return
        self._auto_balance = enabled
        self._invalidate_layout_cache()
        self._images.clear()
        self._expected_image_requests.clear()
        self._load_visible_images()
        self.update()

    def set_auto_balance_only_grow(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._auto_balance_only_grow == enabled:
            return
        self._auto_balance_only_grow = enabled
        self._invalidate_layout_cache()
        self._images.clear()
        self._expected_image_requests.clear()
        self._load_visible_images()
        self.update()

    def viewport_tile_size(self) -> Tuple[int, int]:
        # Average tile size used as a fallback/reference size.
        spacing = CONFIG.grid_tile_spacing
        w = max(1, (self.width() - (self._cols + 1) * spacing) // self._cols)
        h = max(1, (self.height() - (self._rows + 1) * spacing) // self._rows)
        return w, h

    def _invalidate_layout_cache(self) -> None:
        self._cached_col_widths = None
        self._cached_row_heights = None

    def _item_aspect_ratio(self, item: Dict) -> float:
        w = item.get("w")
        h = item.get("h")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            return max(0.05, min(20.0, w / float(h)))
        return 1.0

    def _item_dimensions(self, item: Dict) -> Tuple[float, float]:
        w = item.get("w")
        h = item.get("h")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            return float(w), float(h)
        ratio = self._item_aspect_ratio(item)
        return ratio, 1.0

    def _heuristic_weights(self, axis: str, count: int) -> List[float]:
        if count <= 1:
            return [1.0] * count

        exponent = max(0.0, float(CONFIG.grid_balance_exponent))
        min_factor = float(CONFIG.grid_balance_min_factor)
        max_factor = float(CONFIG.grid_balance_max_factor)
        weights: List[float] = []

        for major in range(count):
            samples: List[float] = []
            minor_count = self._cols if axis == "row" else self._rows
            for minor in range(minor_count):
                row = major if axis == "row" else minor
                col = minor if axis == "row" else major
                index = row * self._cols + col
                if index >= len(self._items):
                    continue
                ratio = self._item_aspect_ratio(self._items[index])
                sample = (1.0 / ratio) ** exponent if axis == "row" else ratio ** exponent
                samples.append(sample)

            weight = (sum(samples) / len(samples)) if samples else 1.0
            weight = max(min_factor, min(max_factor, weight))
            weights.append(weight)

        return weights

    def _blend_weights(self, weights: List[float], alpha: float) -> List[float]:
        alpha = max(0.0, min(1.0, alpha))
        return [1.0 + (weight - 1.0) * alpha for weight in weights]

    def _axis_size_candidates(self, total: int, axis: str, count: int) -> List[List[int]]:
        if count <= 1:
            return [[max(1, total)]]

        min_factor = float(CONFIG.grid_balance_min_factor)
        max_factor = float(CONFIG.grid_balance_max_factor)
        candidates: List[List[int]] = []
        seen: set[Tuple[int, ...]] = set()

        def add_sizes(weights: List[float]) -> None:
            sizes = tuple(self._distribute_sizes(total, weights))
            if sizes not in seen:
                seen.add(sizes)
                candidates.append(list(sizes))

        base_weights = [1.0] * count
        heuristic = self._heuristic_weights(axis, count)
        add_sizes(base_weights)
        add_sizes(heuristic)

        exact_limit = max(1, int(CONFIG.grid_adaptive_exact_search_max_dimension))
        if count <= exact_limit:
            levels = [min_factor, (min_factor + 1.0) * 0.5, 1.0, (1.0 + max_factor) * 0.5, max_factor]
            for combo in product(levels, repeat=count):
                add_sizes(list(combo))
            return candidates

        for alpha in (0.25, 0.5, 0.75):
            add_sizes(self._blend_weights(heuristic, alpha))

        for idx in range(count):
            emphasized = list(heuristic)
            emphasized[idx] = max(min_factor, min(max_factor, emphasized[idx] * 1.18))
            add_sizes(emphasized)

            relaxed = list(heuristic)
            relaxed[idx] = max(min_factor, min(max_factor, 1.0 + (relaxed[idx] - 1.0) * 0.45))
            add_sizes(relaxed)

        return candidates

    def _layout_score(self, col_widths: List[int], row_heights: List[int]) -> Tuple[float, List[float]]:
        total_area = 0.0
        scales: List[float] = []

        for index, item in enumerate(self._items):
            row = index // self._cols
            col = index % self._cols
            if row >= self._rows or col >= self._cols:
                break

            src_w, src_h = self._item_dimensions(item)
            scale = min(col_widths[col] / src_w, row_heights[row] / src_h)
            scale = max(0.0, scale)
            scales.append(scale)
            total_area += (src_w * scale) * (src_h * scale)

        return total_area, scales

    def _distribute_sizes(self, total: int, weights: List[float]) -> List[int]:
        if not weights:
            return []

        total = max(len(weights), total)
        weight_sum = sum(weights) if sum(weights) > 0 else float(len(weights))
        raw = [total * weight / weight_sum for weight in weights]
        sizes = [int(value) for value in raw]
        remainder = total - sum(sizes)
        if remainder > 0:
            order = sorted(range(len(weights)), key=lambda idx: raw[idx] - sizes[idx], reverse=True)
            for idx in order[:remainder]:
                sizes[idx] += 1
        return [max(1, size) for size in sizes]

    def _compute_layout_sizes(self) -> Tuple[List[int], List[int]]:
        spacing = CONFIG.grid_tile_spacing
        inner_width = max(self._cols, self.width() - (self._cols + 1) * spacing)
        inner_height = max(self._rows, self.height() - (self._rows + 1) * spacing)

        baseline_cols = self._distribute_sizes(inner_width, [1.0] * self._cols)
        baseline_rows = self._distribute_sizes(inner_height, [1.0] * self._rows)
        if not self._auto_balance or len(self._items) <= 1:
            return baseline_cols, baseline_rows

        baseline_score, baseline_scales = self._layout_score(baseline_cols, baseline_rows)
        best_cols = baseline_cols
        best_rows = baseline_rows
        best_score = baseline_score

        col_candidates = self._axis_size_candidates(inner_width, "col", self._cols)
        row_candidates = self._axis_size_candidates(inner_height, "row", self._rows)

        for col_sizes in col_candidates:
            for row_sizes in row_candidates:
                score, scales = self._layout_score(col_sizes, row_sizes)
                if self._auto_balance_only_grow and any(
                    scale + 1e-9 < base for scale, base in zip(scales, baseline_scales)
                ):
                    continue
                if score > best_score + 1e-6:
                    best_cols = col_sizes
                    best_rows = row_sizes
                    best_score = score

        return best_cols, best_rows

    def _ensure_layout_cache(self) -> None:
        if (
            self._cached_col_widths is not None
            and self._cached_row_heights is not None
            and len(self._cached_col_widths) == self._cols
            and len(self._cached_row_heights) == self._rows
        ):
            return
        self._cached_col_widths, self._cached_row_heights = self._compute_layout_sizes()

    def _column_widths(self) -> List[int]:
        self._ensure_layout_cache()
        return list(self._cached_col_widths or [])

    def _row_heights(self) -> List[int]:
        self._ensure_layout_cache()
        return list(self._cached_row_heights or [])

    def _tile_rect(self, r: int, c: int) -> QRect:
        if r < 0 or c < 0 or r >= self._rows or c >= self._cols:
            return QRect()
        spacing = CONFIG.grid_tile_spacing
        col_widths = self._column_widths()
        row_heights = self._row_heights()
        if c >= len(col_widths) or r >= len(row_heights):
            self._invalidate_layout_cache()
            col_widths = self._column_widths()
            row_heights = self._row_heights()
        if c >= len(col_widths) or r >= len(row_heights):
            return QRect()
        x = spacing + sum(col_widths[:c]) + c * spacing
        y = spacing + sum(row_heights[:r]) + r * spacing
        return QRect(x, y, col_widths[c], row_heights[r])

    def set_items(self, items: List[Dict]) -> None:
        # items: [{index:int, path:str, status:int}]
        self._items = items
        self._invalidate_layout_cache()
        self._images.clear()
        self._expected_image_requests.clear()
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
        for position, it in enumerate(self._items):
            if it.get("index") == global_index:
                it["status"] = status
                self.update(self._tile_rect(position // self._cols, position % self._cols))
                break

    def _item_at_point(self, pt) -> Optional[Dict]:
        i = 0
        for rr in range(self._rows):
            for cc in range(self._cols):
                if i < len(self._items):
                    rect = self._tile_rect(rr, cc)
                    if rect.contains(pt):
                        return self._items[i]
                i += 1
        return None

    def _drag_transition(self, button, current_status: int) -> Optional[Tuple[int, int]]:
        if button == Qt.LeftButton:
            return current_status, (0 if current_status == 1 else 1)
        if button == Qt.RightButton:
            return current_status, (0 if current_status == -1 else -1)
        return None

    def _reset_drag_state(self) -> None:
        self._drag_button = Qt.NoButton
        self._drag_from_status = None
        self._drag_to_status = None
        self._drag_seen.clear()

    def _apply_drag_to_item(self, item: Dict) -> None:
        if self._drag_button == Qt.NoButton or self._drag_from_status is None or self._drag_to_status is None:
            return

        index = int(item.get("index", -1))
        if index < 0 or index in self._drag_seen:
            return

        self._drag_seen.add(index)
        if int(item.get("status", 0)) != self._drag_from_status:
            return

        item["status"] = self._drag_to_status
        self.cellMarkRequested.emit(index, self._drag_to_status)
        self.update()

    def _load_visible_images(self) -> None:
        if not self._request_image:
            return
        visible_count = min(len(self._items), self._rows * self._cols)
        self._expected_image_requests.clear()
        tile_rects = [
            self._tile_rect(index // self._cols, index % self._cols)
            for index in range(visible_count)
        ]
        # If tiles are not laid out yet (very small), wait for the next resize/layout pass.
        if tile_rects and any(rect.width() < 8 or rect.height() < 8 for rect in tile_rects):
            return

        for index, it in enumerate(self._items[:visible_count]):
            idx = it.get("index")
            path = it.get("path")
            if idx is None or not path:
                continue
            rect = self._tile_rect(index // self._cols, index % self._cols)
            requested_size = (max(1, rect.width()), max(1, rect.height()))
            self._image_request_serial += 1
            token = self._image_request_serial
            self._expected_image_requests[idx] = (token, path, requested_size)

            def make_cb(
                i: int,
                expected_token: int,
                expected_path: str,
                expected_size: Tuple[int, int],
                target_rect: QRect,
            ):
                def _cb(img: QImage):
                    current = self._expected_image_requests.get(i)
                    if current != (expected_token, expected_path, expected_size):
                        return
                    pixmap = QPixmap.fromImage(img)
                    if (
                        not pixmap.isNull()
                        and (pixmap.width() > expected_size[0] or pixmap.height() > expected_size[1])
                    ):
                        pixmap = pixmap.scaled(
                            expected_size[0],
                            expected_size[1],
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation,
                        )
                    self._images[i] = pixmap
                    self.update(target_rect)
                return _cb
            self._request_image(path, requested_size, make_cb(idx, token, path, requested_size, QRect(rect)))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(*CONFIG.background_color))
        dirty_rect = event.rect()
        fm = self.fontMetrics()
        pad_x, pad_y = 6, 2
        gap = 4

        # Draw tiles
        i = 0
        for rr in range(self._rows):
            for cc in range(self._cols):
                rect = self._tile_rect(rr, cc)
                if not rect.intersects(dirty_rect):
                    i += 1
                    continue
                # Draw background for tile
                p.fillRect(rect, QColor(*CONFIG.tile_background_color))
                if i < len(self._items):
                    item = self._items[i]
                    pm = self._images.get(item.get("index", -1))
                    if pm is not None and not pm.isNull():
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
            tw = fm.horizontalAdvance(text) + metrics_padding * 2
            th = fm.height() + metrics_padding
            rect = QRect(8, 8, tw, th)
            # Badge background with semi-transparency
            if rect.intersects(dirty_rect):
                p.fillRect(rect, QColor(0, 0, 0, 140))
                p.setPen(QColor(230, 230, 230))
                p.drawText(rect.adjusted(metrics_padding, 0, -metrics_padding, 0), Qt.AlignVCenter | Qt.AlignLeft, text)

        # If showing paths, draw under each tile
        if self._show_paths:
            i = 0
            for rr in range(self._rows):
                for cc in range(self._cols):
                    if i < len(self._items):
                        item = self._items[i]
                        rect = self._tile_rect(rr, cc)
                        if not rect.intersects(dirty_rect):
                            i += 1
                            continue
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
        self._invalidate_layout_cache()
        self._images.clear()
        self._expected_image_requests.clear()
        self._load_visible_images()
        super().resizeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        item = self._item_at_point(pos)
        if item is not None:
            cur = int(item.get("status", 0))
            transition = self._drag_transition(event.button(), cur)
            if transition is not None:
                self._drag_button = event.button()
                self._drag_from_status, self._drag_to_status = transition
                self._drag_seen.clear()
                self._apply_drag_to_item(item)
                return
            if event.button() == Qt.MiddleButton:
                index = int(item.get("index"))
                if event.modifiers() & Qt.ShiftModifier:
                    self.openExternalRequested.emit(index)
                else:
                    self.contextMenuRequested.emit(index, event.globalPosition().toPoint())
                return
        self._reset_drag_state()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_button == Qt.NoButton:
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & self._drag_button):
            self._reset_drag_state()
            super().mouseMoveEvent(event)
            return

        item = self._item_at_point(event.position().toPoint())
        if item is not None:
            self._apply_drag_to_item(item)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == self._drag_button:
            self._reset_drag_state()
        super().mouseReleaseEvent(event)

    def index_at_point(self, pt) -> Optional[int]:
        # Returns global index for cell under point, or None
        item = self._item_at_point(pt)
        if item is None:
            return None
        return int(item.get("index"))
