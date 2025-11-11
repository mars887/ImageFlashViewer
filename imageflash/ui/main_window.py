from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal, Slot, QEvent
from PySide6.QtGui import QAction, QKeySequence, QKeyEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QSplitter,
    QMessageBox,
    QStackedWidget,
)
from PySide6.QtGui import QShortcut

from ..data.repo import SQLiteRepository
from ..services.scanner import scan_images
from ..services.preloader import ImagePreloader
from ..state.store import ImageStore
from .sidebar import SideBar
from .view_single import ViewSingleWidget
from .view_grid import ViewGridWidget
from ..config import CONFIG
from .overlay import OverlayWidget


class MainWindow(QMainWindow):
    def __init__(self, group_images: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("ImageFlashViewer")

        # Core state/services
        self.repo: Optional[SQLiteRepository] = None
        self.store = ImageStore()
        self.preloader = ImagePreloader(CONFIG.preloader_max_items)
        self.group_images = group_images
        self.grid_cols = 1
        self.grid_rows = 1
        self._sign_mode = None  # type: Optional[int]
        self._del_held = False
        self._overlay_forced_index = None  # type: Optional[int]
        self._is_minus_held = False
        self._is_clear_held = False

        # UI setup
        self.sidebar = SideBar()
        self.viewer = ViewSingleWidget()
        self.grid_view = ViewGridWidget()
        self.grid_view.set_request_image(self.preloader.request)
        self.overlay = OverlayWidget(self)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.viewer)
        self.stack.addWidget(self.grid_view)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        # Actions and shortcuts
        self._setup_actions()

        # Wiring
        self.sidebar.folderSelected.connect(self.on_folder_selected)
        self.sidebar.gridSizeChanged.connect(self.on_grid_size_changed)
        self.store.currentChanged.connect(self.on_current_changed)
        self.store.statsChanged.connect(self.sidebar.update_stats)

        # When viewer resizes, we may request a better sized image
        self.viewer.requestRescale.connect(self._refresh_current_image)
        self.grid_view.requestRescale.connect(self._refresh_grid_page)
        self.grid_view.cellMarkRequested.connect(self.on_grid_cell_mark)

        # Grid shortcuts
        self._setup_grid_shortcuts()

        # Event filters to update overlay while moving mouse
        self.viewer.installEventFilter(self)
        self.grid_view.installEventFilter(self)

    def _setup_actions(self) -> None:
        # Fullscreen toggle (F11)
        act_fullscreen = QAction("Toggle Fullscreen", self)
        act_fullscreen.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.toggle_fullscreen])
        act_fullscreen.triggered.connect(self.toggle_fullscreen)
        self.addAction(act_fullscreen)

        # Navigation
        act_prev = QAction("Prev", self)
        act_prev.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.prev])
        act_prev.triggered.connect(self.on_prev)
        self.addAction(act_prev)

        act_next = QAction("Next", self)
        act_next.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.next])
        act_next.triggered.connect(self.on_next)
        self.addAction(act_next)

        # Mark positive (Up) / negative (Down)
        act_mark_pos = QAction("Mark Positive", self)
        act_mark_pos.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.mark_positive])
        act_mark_pos.triggered.connect(lambda: self.on_mark(+1))
        self.addAction(act_mark_pos)

        act_mark_neg = QAction("Mark Negative", self)
        act_mark_neg.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.mark_negative])
        act_mark_neg.triggered.connect(lambda: self.on_mark(-1))
        self.addAction(act_mark_neg)

    def _setup_grid_shortcuts(self) -> None:
        for s in CONFIG.hotkeys.grid_mark_negative_batch:
            sc = QShortcut(QKeySequence(s), self)
            sc.activated.connect(lambda st=-1: self.on_grid_mark_batch(st))
        for s in CONFIG.hotkeys.grid_mark_positive_batch:
            sc = QShortcut(QKeySequence(s), self)
            sc.activated.connect(lambda st=+1: self.on_grid_mark_batch(st))
        for s in CONFIG.hotkeys.grid_next_page:
            sc = QShortcut(QKeySequence(s), self)
            sc.activated.connect(self.on_grid_next_page)
        for s in CONFIG.hotkeys.grid_prefill_next_positive:
            sc = QShortcut(QKeySequence(s), self)
            sc.activated.connect(self.on_grid_prefill_next_positive)

    # Slots / Handlers
    @Slot(str)
    def on_folder_selected(self, folder: str) -> None:
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Папка не найдена", f"Путь не существует: {folder}")
            return

        # Init repo and DB
        self.repo = SQLiteRepository(folder, group_images=self.group_images)
        self.repo.init()

        # Scan and sync
        filenames = scan_images(folder, grouped=self.group_images)
        removed = self.repo.sync_with_folder(filenames)

        # Load records and init store
        records = self.repo.get_all_records()
        if self.group_images:
            # Ensure on-disk grouping matches DB statuses
            self.repo.enforce_grouping_for_all()
        self.store.load_records(records)

        if not records:
            QMessageBox.information(self, "Нет изображений", "В выбранной папке нет поддерживаемых изображений.")
            return

        # Show first view based on mode
        self._apply_view_mode()

    @Slot()
    def on_prev(self) -> None:
        if self._is_grid_mode():
            if self.store.prev_page(self.grid_rows, self.grid_cols):
                self._refresh_grid_page()
        else:
            if self.store.prev():
                self._refresh_current_image()
                self._preload_neighbors()

    @Slot()
    def on_next(self) -> None:
        if self._is_grid_mode():
            if self.store.next_page(self.grid_rows, self.grid_cols):
                self._refresh_grid_page()
        else:
            if self.store.next():
                self._refresh_current_image()
                self._preload_neighbors()

    @Slot()
    def on_mark(self, status: int) -> None:
        if self.repo is None:
            return
        if self._is_grid_mode():
            # Mark only unreviewed in current grid and go to next page
            self._grid_mark_all(status, only_unreviewed=True)
            self.on_grid_next_page()
        else:
            changed = self.store.mark_status(status, self.repo)
            if changed:
                # If grouping is enabled, move current file to its folder
                if self.group_images and self.repo:
                    rec = self.store.current_record()
                    if rec:
                        try:
                            self.repo.move_file_to_group(rec['filename'], status)
                        except Exception:
                            pass
                # Auto-advance to next unreviewed
                if not self.store.goto_next_unreviewed():
                    # If none, just go next
                    self.store.next()
                self._refresh_current_image()
                self._preload_neighbors()

    @Slot(int, int)
    def on_current_changed(self, index: int, status: int) -> None:
        # Update status stripe
        if self._is_grid_mode():
            self._refresh_grid_page()
        else:
            self.viewer.set_status(status)

    def _current_file_abspath(self) -> Optional[str]:
        rec = self.store.current_record()
        if not rec or not self.repo:
            return None
        return self.repo.abspath_for(rec['filename'], rec.get('status'))

    def _refresh_current_image(self) -> None:
        path = self._current_file_abspath()
        if not path:
            return
        vw, vh = self.viewer.viewport_size()
        if vw <= 0 or vh <= 0:
            return
        # Request from preloader
        self.preloader.request(path, (vw, vh), self.viewer.set_image)

    def _preload_neighbors(self, radius: int = None) -> None:
        if not self.repo:
            return
        vw, vh = self.viewer.viewport_size()
        if vw <= 0 or vh <= 0:
            return
        if radius is None:
            radius = CONFIG.preload_radius
        indices = self.store.neighbor_indices(radius)
        for idx in indices:
            rec = self.store.record_at(idx)
            if not rec:
                continue
            path = self.repo.abspath_for(rec['filename'], rec.get('status'))
            self.preloader.request(path, (vw, vh))

    @Slot()
    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        if hasattr(self, 'overlay'):
            self.overlay.setGeometry(self.rect())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, 'overlay'):
            self.overlay.setGeometry(self.rect())

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.MouseMove and self._del_held:
            self._overlay_forced_index = None
            self._update_overlay_image()
        return super().eventFilter(obj, event)
        self._layout_overlay()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_overlay()

    def _layout_overlay(self) -> None:
        if hasattr(self, 'overlay') and self.overlay:
            self.overlay.setGeometry(self.rect())

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.MouseMove and self._del_held:
            self._update_overlay_image()
        return super().eventFilter(obj, event)

    # Grid helpers and handlers
    def _is_grid_mode(self) -> bool:
        return not (self.grid_cols == 1 and self.grid_rows == 1)

    @Slot(int, int)
    def on_grid_size_changed(self, cols: int, rows: int) -> None:
        self.grid_cols = cols
        self.grid_rows = rows
        self._apply_view_mode()

    def _apply_view_mode(self) -> None:
        if self._is_grid_mode():
            self.stack.setCurrentWidget(self.grid_view)
            self.grid_view.set_grid_size(self.grid_cols, self.grid_rows)
            self._refresh_grid_page()
        else:
            self.stack.setCurrentWidget(self.viewer)
            self._refresh_current_image()
            self._preload_neighbors()

    def _refresh_grid_page(self) -> None:
        if not self.repo:
            return
        items = []
        base_index = self.store.index()
        recs = self.store.current_page_records(self.grid_rows, self.grid_cols)
        for offset, rec in enumerate(recs):
            idx = base_index + offset
            path = self.repo.abspath_for(rec['filename'], rec.get('status'))
            items.append({"index": idx, "path": path, "status": rec.get('status', 0)})
        self.grid_view.set_items(items)
        # Badge info
        total = len(self.store.records())
        start = base_index + 1 if total > 0 else 0
        end = base_index + len(recs)
        self.grid_view.set_page_info(start, end, total)

    @Slot(int, int)
    def on_grid_cell_mark(self, global_index: int, new_status: int) -> None:
        if not self.repo:
            return
        changed = self.store.mark_status_at(global_index, new_status, self.repo)
        if changed:
            if self.group_images and self.repo:
                rec = self.store.record_at(global_index)
                if rec:
                    try:
                        self.repo.move_file_to_group(rec['filename'], new_status)
                    except Exception:
                        pass
            self.grid_view.update_item_status(global_index, new_status)

    def _grid_mark_all(self, status: int, only_unreviewed: bool = False) -> None:
        if not self.repo:
            return
        indices = self.store.page_indices(self.grid_rows, self.grid_cols)
        for i in indices:
            rec = self.store.record_at(i)
            if not rec:
                continue
            if only_unreviewed and int(rec.get('status', 0)) != 0:
                continue
            if self.store.mark_status_at(i, status, self.repo):
                if self.group_images:
                    try:
                        self.repo.move_file_to_group(rec['filename'], status)
                    except Exception:
                        pass
        self._refresh_grid_page()

    @Slot()
    def on_grid_next_page(self) -> None:
        if self.store.next_page(self.grid_rows, self.grid_cols):
            self._refresh_grid_page()

    def on_grid_mark_batch(self, status: int) -> None:
        if not self._is_grid_mode():
            return
        recs = self.store.current_page_records(self.grid_rows, self.grid_cols)
        any_unreviewed = any(int(r.get('status', 0)) == 0 for r in recs)
        self._grid_mark_all(status, only_unreviewed=any_unreviewed)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in CONFIG.hotkeys.overlay_hold_keys:
            if not self._del_held:
                self._del_held = True
                self.overlay.show_overlay()
                self.overlay.setGeometry(self.rect())
                self._update_overlay_image()
                return
        if self._is_grid_mode():
            key = event.key()
            # Update chord flags for clear+minus
            if key in CONFIG.hotkeys.sign_minus_keys:
                self._is_minus_held = True
            if key in CONFIG.hotkeys.sign_clear_keys:
                self._is_clear_held = True
            # Chord: clear entire grid
            if self._is_minus_held and self._is_clear_held:
                self._grid_mark_all(0, only_unreviewed=False)
                return
            # Single-sign mode for per-cell operations
            if key in (CONFIG.hotkeys.sign_plus_keys + CONFIG.hotkeys.sign_minus_keys + CONFIG.hotkeys.sign_clear_keys):
                if key in CONFIG.hotkeys.sign_plus_keys:
                    self._sign_mode = 1
                elif key in CONFIG.hotkeys.sign_minus_keys:
                    self._sign_mode = -1
                elif key in CONFIG.hotkeys.sign_clear_keys:
                    self._sign_mode = 0
                return
            if key in CONFIG.hotkeys.grid_digit_keys:
                if self._del_held:
                    idx = self._index_for_numpad_key(key)
                    if idx is not None:
                        self._overlay_forced_index = idx
                        self._update_overlay_image()
                        return
                self._handle_numpad_digit(key)
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (CONFIG.hotkeys.sign_plus_keys + CONFIG.hotkeys.sign_minus_keys + CONFIG.hotkeys.sign_clear_keys):
            self._sign_mode = None
            if event.key() in CONFIG.hotkeys.sign_minus_keys:
                self._is_minus_held = False
            if event.key() in CONFIG.hotkeys.sign_clear_keys:
                self._is_clear_held = False
        if event.key() in CONFIG.hotkeys.overlay_hold_keys:
            self._del_held = False
            self._overlay_forced_index = None
            self.overlay.hide_overlay()
            return
        super().keyReleaseEvent(event)

    @Slot()
    def on_grid_prefill_next_positive(self) -> None:
        if not self._is_grid_mode() or not self.repo:
            return
        page_size = self.grid_rows * self.grid_cols
        total = len(self.store.records())
        if total == 0 or page_size <= 0:
            return
        base = self.store.index()
        last_start = max(0, total - page_size)
        next_start = min(last_start, base + page_size)
        # If there is no next page, do nothing
        if next_start == base:
            return
        end = min(total, next_start + page_size)

        # Decide marking mode for next page
        forced = None
        if self._sign_mode == 1:
            forced = 1
        elif self._sign_mode == -1:
            forced = -1

        for idx in range(next_start, end):
            rec = self.store.record_at(idx)
            if not rec:
                continue
            if forced is None:
                if int(rec.get('status', 0)) != 0:
                    continue
                new_status = 1
            else:
                new_status = forced
            if self.store.mark_status_at(idx, new_status, self.repo):
                if self.group_images:
                    try:
                        self.repo.move_file_to_group(rec['filename'], new_status)
                    except Exception:
                        pass

        # Navigate to next page after prefill
        self.store.set_index(next_start)
        self._refresh_grid_page()

    def _index_for_numpad_key(self, key: int):
        key_to_rc = {
            Qt.Key_7: (0, 0), Qt.Key_8: (0, 1), Qt.Key_9: (0, 2),
            Qt.Key_4: (1, 0), Qt.Key_5: (1, 1), Qt.Key_6: (1, 2),
            Qt.Key_1: (2, 0), Qt.Key_2: (2, 1), Qt.Key_3: (2, 2),
        }
        rc = key_to_rc.get(key)
        if not rc:
            return None
        r, c = rc
        if r >= self.grid_rows or c >= self.grid_cols:
            return None
        base = self.store.index()
        return base + r * self.grid_cols + c

    def _update_overlay_image(self) -> None:
        if not self.repo:
            return
        # Size for overlay content
        vw, vh = self.overlay.viewport_size()
        target_path = None
        if self._is_grid_mode():
            if self._overlay_forced_index is not None:
                idx = self._overlay_forced_index
            else:
                # Determine which grid cell the mouse is over
                pos = self.grid_view.mapFromGlobal(self.cursor().pos())
                idx = self.grid_view.index_at_point(pos)
            if idx is not None:
                rec = self.store.record_at(idx)
                if rec:
                    target_path = self.repo.abspath_for(rec['filename'], rec.get('status'))
        else:
            rec = self.store.current_record()
            if rec:
                target_path = self.repo.abspath_for(rec['filename'], rec.get('status'))
        if not target_path:
            self.overlay.set_image(None)
            return
        self.preloader.request(target_path, (vw, vh), self.overlay.set_image)

    def _handle_numpad_digit(self, key: int) -> None:
        idx = self._index_for_numpad_key(key)
        if idx is None:
            return
        rec = self.store.record_at(idx)
        if not rec or not self.repo:
            return
        cur = int(rec.get('status', 0))
        if self._sign_mode is None:
            new_st = 1 if cur == 0 else (-1 if cur == 1 else 0)
        else:
            new_st = self._sign_mode
        self.on_grid_cell_mark(idx, new_st)
