from __future__ import annotations

import os
import sys
import subprocess
import shutil
from typing import Optional, Tuple

from PySide6.QtCore import Qt, Slot, QEvent, QPoint, QTimer
from PySide6.QtGui import QAction, QKeySequence, QKeyEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QMessageBox,
    QStackedWidget,
    QMenu,
    QFileDialog,
    QWidget,
    QVBoxLayout,
)
from PySide6.QtGui import QShortcut

from ..data.repo import SQLiteRepository
from ..services.scanner import scan_images
from ..services.preloader import ImagePreloader
from ..state.store import ImageStore
from .sidebar import SideBar
from .top_menu import TopMenuWidget
from .view_single import ViewSingleWidget
from .view_grid import ViewGridWidget
from ..config import CONFIG
from .overlay import OverlayWidget
from PySide6.QtGui import QImageReader

# Developer Notes (ui/main_window.py)
# - MainWindow orchestrates the UI: sidebar, single viewer, grid view and
#   overlay. It wires hotkeys, navigation, marking, grouping moves, preloading,
#   and optional path labels. Grid size is controlled via sidebar sliders.
# - Grid mode: per-tile clicks mark individual statuses; batch operations via
#   shortkeys; Enter/Left/Right page navigation; Space prefill next page.
# - Overlay: hold overlay key(s) to preview under cursor; footer shows
#   path/file size/dimensions; numpad targeting supported while overlay is held.
# - Keep long operations off the GUI thread; use preloader for image IO.


class MainWindow(QMainWindow):
    def __init__(self, group_images: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("ImageFlashViewer")

        # Core state/services
        self.repo: Optional[SQLiteRepository] = None
        self.store = ImageStore()
        self.preloader = ImagePreloader(CONFIG.preloader_max_items)
        self.group_images = group_images
        self.grid_cols = CONFIG.grid_default_cols
        self.grid_rows = CONFIG.grid_default_rows
        self._grid_auto_balance = bool(CONFIG.grid_auto_balance)
        self._grid_auto_balance_only_grow = bool(CONFIG.grid_auto_balance_only_grow)
        self._sign_mode = None  # type: Optional[int]
        self._del_held = False
        self._overlay_forced_index = None  # type: Optional[int]
        self._is_minus_held = False
        self._is_clear_held = False
        self._show_paths = False
        self._show_info_master = False
        self._show_info_res = False
        self._show_info_size = False
        self._show_info_fmt = False
        self._viewer_request_id = 0
        self._overlay_request_id = 0
        self._overlay_last_path: Optional[str] = None
        self._overlay_last_footer: Optional[str] = None

        # UI setup
        self.top_menu = TopMenuWidget()
        self.sidebar = SideBar()
        self.viewer = ViewSingleWidget()
        self.grid_view = ViewGridWidget()
        self.grid_view.set_auto_balance(self._grid_auto_balance)
        self.grid_view.set_auto_balance_only_grow(self._grid_auto_balance_only_grow)
        self.grid_view.set_request_image(self.preloader.request)
        self.overlay = OverlayWidget(self)
        # Ensure viewers can take focus for keyboard navigation
        self.viewer.setFocusPolicy(Qt.StrongFocus)
        self.grid_view.setFocusPolicy(Qt.StrongFocus)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.viewer)
        self.stack.addWidget(self.grid_view)

        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self.top_menu)
        left_layout.addWidget(self.sidebar, 1)
        self.left_panel.setMinimumWidth(360)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        # Actions and shortcuts
        self._setup_actions()

        # Wiring
        self.top_menu.folderSelected.connect(self.on_folder_selected)
        self.sidebar.gridSizeChanged.connect(self.on_grid_size_changed)
        self.sidebar.gridAutoBalanceToggled.connect(self.on_grid_auto_balance_toggled)
        self.sidebar.gridAutoBalanceOnlyGrowToggled.connect(self.on_grid_auto_balance_only_grow_toggled)
        self.top_menu.showPathsToggled.connect(self.on_show_paths_toggled)
        self.sidebar.jumpToFirstUnreviewed.connect(self.on_jump_to_first_unreviewed)
        self.top_menu.showInfoToggled.connect(self.on_show_info_master_toggled)
        self.top_menu.showInfoResToggled.connect(self.on_show_info_res_toggled)
        self.top_menu.showInfoSizeToggled.connect(self.on_show_info_size_toggled)
        self.top_menu.showInfoFmtToggled.connect(self.on_show_info_fmt_toggled)
        self.top_menu.exportStatusTo.connect(self.on_export_status_to)
        self.top_menu.deleteNegativeRequested.connect(self.on_delete_negative_requested)
        self.store.currentChanged.connect(self.on_current_changed)
        self.store.statsChanged.connect(self.sidebar.update_stats)

        # When viewer resizes, we may request a better sized image
        self.viewer.requestRescale.connect(self._refresh_current_image)
        self.grid_view.requestRescale.connect(self._refresh_grid_page)
        self.grid_view.cellMarkRequested.connect(self.on_grid_cell_mark)
        self.grid_view.openExternalRequested.connect(self.on_grid_open_external)
        self.grid_view.contextMenuRequested.connect(self.on_grid_context_menu)

        # Grid shortcuts
        self._setup_grid_shortcuts()

        # Event filters to update overlay while moving mouse
        self._install_overlay_filters(self.viewer)
        self._install_overlay_filters(self.grid_view)
        self._install_overlay_filters(self.left_panel)

    def _setup_actions(self) -> None:
        # Fullscreen toggle (F11)
        act_fullscreen = QAction("Toggle Fullscreen", self)
        act_fullscreen.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.toggle_fullscreen])
        act_fullscreen.setShortcutContext(Qt.ApplicationShortcut)
        act_fullscreen.triggered.connect(self.toggle_fullscreen)
        self.addAction(act_fullscreen)

        # Navigation
        act_prev = QAction("Prev", self)
        act_prev.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.prev])
        act_prev.setShortcutContext(Qt.ApplicationShortcut)
        act_prev.triggered.connect(self.on_prev)
        self.addAction(act_prev)

        act_next = QAction("Next", self)
        act_next.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.next])
        act_next.setShortcutContext(Qt.ApplicationShortcut)
        act_next.triggered.connect(self.on_next)
        self.addAction(act_next)

        # Mark positive (Up) / negative (Down)
        act_mark_pos = QAction("Mark Positive", self)
        act_mark_pos.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.mark_positive])
        act_mark_pos.setShortcutContext(Qt.ApplicationShortcut)
        act_mark_pos.triggered.connect(lambda: self.on_mark(+1))
        self.addAction(act_mark_pos)

        act_mark_neg = QAction("Mark Negative", self)
        act_mark_neg.setShortcuts([QKeySequence(s) for s in CONFIG.hotkeys.mark_negative])
        act_mark_neg.setShortcutContext(Qt.ApplicationShortcut)
        act_mark_neg.triggered.connect(lambda: self.on_mark(-1))
        self.addAction(act_mark_neg)

    def _setup_grid_shortcuts(self) -> None:
        for s in CONFIG.hotkeys.grid_mark_negative_batch:
            sc = QShortcut(QKeySequence(s), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(lambda st=-1: self.on_grid_mark_batch(st))
        for s in CONFIG.hotkeys.grid_mark_positive_batch:
            sc = QShortcut(QKeySequence(s), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(lambda st=+1: self.on_grid_mark_batch(st))
        for s in CONFIG.hotkeys.grid_next_page:
            sc = QShortcut(QKeySequence(s), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self.on_grid_next_page)
        for s in CONFIG.hotkeys.grid_prefill_next_positive:
            sc = QShortcut(QKeySequence(s), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self.on_grid_prefill_next_positive)

    def _install_overlay_filters(self, root: QWidget) -> None:
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

    # Slots / Handlers
    @Slot(str)
    def on_folder_selected(self, folder: str) -> None:
        if not os.path.isdir(folder):
            QMessageBox.warning(self, "Папка не найдена", f"Путь не существует: {folder}")
            return

        # Init repo and DB
        self.repo = SQLiteRepository(folder, group_images=self.group_images)
        self.repo.init()
        self.preloader.clear_size_cache()

        # Reflect selected path in sidebar
        try:
            self.top_menu.set_path(folder)
        except Exception:
            pass

        # Scan and sync
        filenames = scan_images(folder, grouped=self.group_images)
        self.repo.sync_with_folder(filenames)

        # Load records and init store
        records = self.repo.get_all_records()
        if self.group_images:
            # Ensure on-disk grouping matches DB statuses
            self.repo.enforce_grouping_for_all()
        self.grid_view.set_grid_size(self.grid_cols, self.grid_rows)
        self.store.load_records(records)

        if not records:
            self._apply_view_mode()
            QMessageBox.information(self, "Нет изображений", "В выбранной папке нет поддерживаемых изображений.")
            return

        # Show first view based on mode
        self._apply_view_mode()
        # After layout settles, refresh the grid again to lock correct tile sizes
        if self._is_grid_mode():
            QTimer.singleShot(0, self._refresh_grid_page)
        # Move focus to the active viewer so shortcuts are not eaten by the path field
        if self._is_grid_mode():
            self.grid_view.setFocus(Qt.OtherFocusReason)
        else:
            self.viewer.setFocus(Qt.OtherFocusReason)

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

    @Slot(int, str)
    def on_export_status_to(self, status: int, out_dir: str) -> None:
        if not self.repo:
            return
        moved = 0
        try:
            moved = self.repo.export_move_by_status(status, out_dir)
        except Exception:
            moved = 0
        # Reload records from DB after changes
        try:
            records = self.repo.get_all_records()
            self.store.load_records(records)
            self._apply_view_mode()
        except Exception:
            pass
        # Notify
        try:
            name = "positive" if status > 0 else ("negative" if status < 0 else "unfiltered")
            QMessageBox.information(self, "Export", f"Moved {moved} {name} image(s).")
        except Exception:
            pass

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

    @Slot()
    def on_delete_negative_requested(self) -> None:
        if not self.repo:
            return
        count = 0
        try:
            count = self.repo.delete_negative()
        except Exception:
            count = 0
        # Reload after deletion
        try:
            records = self.repo.get_all_records()
            self.store.load_records(records)
            self._apply_view_mode()
        except Exception:
            pass
        try:
            QMessageBox.information(self, "Delete Negative", f"Deleted {count} negative image(s).")
        except Exception:
            pass

    @Slot(int, int)
    def on_current_changed(self, index: int, status: int) -> None:
        # Update status stripe
        if self._is_grid_mode():
            self._refresh_grid_page()
        else:
            self.viewer.set_status(status)
            # Update path overlay if showing paths
            rec = self.store.current_record()
            if self._show_paths and self.repo and rec:
                path = self.repo.abspath_for(rec['filename'], rec.get('status'))
                rel = os.path.relpath(path, self.repo.folder)
                self.viewer.set_path_text(rel)
            else:
                self.viewer.set_path_text(None)
        if self._del_held:
            self._refresh_overlay_preview()

    def _current_file_abspath(self) -> Optional[str]:
        rec = self.store.current_record()
        if not rec or not self.repo:
            return None
        return self.repo.abspath_for(rec['filename'], rec.get('status'))

    def _read_image_dimensions(self, path: str) -> Optional[Tuple[int, int]]:
        try:
            reader = QImageReader(path)
            sz = reader.size()
            if sz.isValid() and sz.width() > 0 and sz.height() > 0:
                return sz.width(), sz.height()
        except Exception:
            return None
        return None

    def _image_dimensions(self, path: str, blocking: bool = False) -> Optional[Tuple[int, int]]:
        cached, size = self.preloader.get_cached_size(path)
        if cached:
            return size
        if not blocking:
            self.preloader.request_size(path)
            return None
        size = self._read_image_dimensions(path)
        self.preloader.prime_size(path, size)
        return size

    def _warm_grid_dimensions(self, start_index: int, page_count: int = 2) -> None:
        if not self.repo:
            return
        if not (self._grid_auto_balance or (self._show_info_master and self._show_info_res)):
            return
        page_size = max(1, self.grid_rows * self.grid_cols)
        start_index = max(0, start_index)
        end_index = min(len(self.store.records()), start_index + page_size * max(1, page_count))
        for idx in range(start_index, end_index):
            rec = self.store.record_at(idx)
            if not rec:
                continue
            path = self.repo.abspath_for(rec['filename'], rec.get('status'))
            self.preloader.request_size(path)

    def _refresh_current_image(self) -> None:
        path = self._current_file_abspath()
        if not path:
            self._viewer_request_id += 1
            self.viewer.set_image(None)
            return
        vw, vh = self.viewer.viewport_size()
        if vw <= 0 or vh <= 0:
            return

        self._viewer_request_id += 1
        request_id = self._viewer_request_id

        def _set_current_image(image):
            if request_id != self._viewer_request_id:
                return
            if path != self._current_file_abspath():
                return
            self.viewer.set_image(image)

        # Request from preloader
        self.preloader.request(path, (vw, vh), _set_current_image)

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
        self._layout_overlay()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_overlay()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.MouseMove and self._del_held:
            self._overlay_forced_index = None
            self._refresh_overlay_preview()
        return super().eventFilter(obj, event)

    def _layout_overlay(self) -> None:
        if hasattr(self, 'overlay') and self.overlay:
            self.overlay.setGeometry(self.rect())

    def _cursor_in_left_panel(self) -> bool:
        local_pos = self.mapFromGlobal(self.cursor().pos())
        return self.left_panel.geometry().contains(local_pos)

    def _hide_overlay_preview(self, clear_last: bool = False) -> None:
        self._overlay_request_id += 1
        self.overlay.set_image(None)
        self.overlay.set_footer(None)
        self.overlay.hide_overlay()
        if clear_last:
            self._overlay_last_path = None
            self._overlay_last_footer = None

    def _overlay_payload_for_record(self, rec) -> tuple[Optional[str], Optional[str]]:
        if not self.repo or not rec:
            return None, None

        target_path = self.repo.abspath_for(rec['filename'], rec.get('status'))
        rel = os.path.relpath(target_path, self.repo.folder)
        size_text = ""
        try:
            size_bytes = os.path.getsize(target_path)
            size_text = self._format_bytes(size_bytes)
        except Exception:
            size_text = "?"
        wh_text = ""
        size = self._image_dimensions(target_path, blocking=True)
        if size:
            wh_text = f"{size[0]}x{size[1]}"

        footer = f"{rel}"
        if size_text:
            footer += f" • {size_text}"
        if wh_text:
            footer += f" • {wh_text}"
        return target_path, footer

    def _refresh_overlay_preview(self) -> None:
        if not self.repo or not self._del_held:
            return
        if self._cursor_in_left_panel():
            self._hide_overlay_preview(clear_last=False)
            return

        vw, vh = self.overlay.viewport_size()
        target_path = None
        footer = None

        if self._is_grid_mode():
            if self._overlay_forced_index is not None:
                idx = self._overlay_forced_index
            else:
                pos = self.grid_view.mapFromGlobal(self.cursor().pos())
                idx = self.grid_view.index_at_point(pos) if self.grid_view.rect().contains(pos) else None
            if idx is not None:
                rec = self.store.record_at(idx)
                if rec:
                    target_path, footer = self._overlay_payload_for_record(rec)
            elif self._overlay_last_path:
                target_path = self._overlay_last_path
                footer = self._overlay_last_footer
        else:
            rec = self.store.current_record()
            if rec:
                target_path, footer = self._overlay_payload_for_record(rec)

        if not target_path:
            self._hide_overlay_preview(clear_last=False)
            return

        self._overlay_last_path = target_path
        self._overlay_last_footer = footer
        self.overlay.set_footer(footer)
        self.overlay.show_overlay()

        self._overlay_request_id += 1
        request_id = self._overlay_request_id

        def _set_overlay_image(image):
            if request_id != self._overlay_request_id:
                return
            self.overlay.set_image(image)

        self.preloader.request(target_path, (vw, vh), _set_overlay_image)

    # Grid helpers and handlers
    def _is_grid_mode(self) -> bool:
        return not (self.grid_cols == 1 and self.grid_rows == 1)

    @Slot(int, int)
    def on_grid_size_changed(self, cols: int, rows: int) -> None:
        self.grid_cols = cols
        self.grid_rows = rows
        self._apply_view_mode()

    @Slot(bool)
    def on_grid_auto_balance_toggled(self, enabled: bool) -> None:
        self._grid_auto_balance = bool(enabled)
        self.grid_view.set_auto_balance(self._grid_auto_balance)
        if self._is_grid_mode():
            self._refresh_grid_page()

    @Slot(bool)
    def on_grid_auto_balance_only_grow_toggled(self, enabled: bool) -> None:
        self._grid_auto_balance_only_grow = bool(enabled)
        self.grid_view.set_auto_balance_only_grow(self._grid_auto_balance_only_grow)
        if self._is_grid_mode():
            self._refresh_grid_page()

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
        base_index = self.store.index()
        if base_index < 0:
            self.grid_view.set_items([])
            self.grid_view.set_page_info(0, 0, len(self.store.records()))
            self.grid_view.set_show_paths(self._show_paths)
            self.grid_view.set_show_info_res(self._show_info_res if self._show_info_master else False)
            self.grid_view.set_show_info_size(self._show_info_size if self._show_info_master else False)
            self.grid_view.set_show_info_fmt(self._show_info_fmt if self._show_info_master else False)
            return

        items = []
        recs = self.store.current_page_records(self.grid_rows, self.grid_cols)
        need_dimensions = self._grid_auto_balance or (self._show_info_master and self._show_info_res)
        need_paths = self._show_paths
        need_info_size = self._show_info_master and self._show_info_size
        need_info_fmt = self._show_info_master and self._show_info_fmt
        for offset, rec in enumerate(recs):
            idx = base_index + offset
            path = self.repo.abspath_for(rec['filename'], rec.get('status'))
            item = {"index": idx, "path": path, "status": rec.get('status', 0)}
            if need_paths:
                item["rel"] = os.path.relpath(path, self.repo.folder)
            if need_dimensions:
                size = self._image_dimensions(path, blocking=True)
                if size:
                    item["w"] = size[0]
                    item["h"] = size[1]
            if need_info_size:
                try:
                    kb = max(0, int(os.path.getsize(path) / 1024))
                    item["size_kb"] = kb
                except Exception:
                    pass
            if need_info_fmt:
                try:
                    ext = os.path.splitext(path)[1][1:].upper()
                    item["fmt"] = ext
                except Exception:
                    pass
            items.append(item)
        self.grid_view.set_items(items)
        # Badge info
        total = len(self.store.records())
        start = base_index + 1 if total > 0 else 0
        end = base_index + len(recs)
        self.grid_view.set_page_info(start, end, total)
        self.grid_view.set_show_paths(self._show_paths)
        self.grid_view.set_show_info_res(self._show_info_res if self._show_info_master else False)
        self.grid_view.set_show_info_size(self._show_info_size if self._show_info_master else False)
        self.grid_view.set_show_info_fmt(self._show_info_fmt if self._show_info_master else False)
        self._warm_grid_dimensions(base_index + len(recs))

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
                self._refresh_grid_page()
            else:
                self.grid_view.update_item_status(global_index, new_status)
            if self._del_held:
                self._refresh_overlay_preview()

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

    @Slot(int)
    def on_grid_open_external(self, global_index: int) -> None:
        if not self.repo:
            return
        rec = self.store.record_at(global_index)
        if not rec:
            return
        path = self.repo.abspath_for(rec['filename'], rec.get('status'))
        self._open_external(path)

    def _open_external(self, path: str) -> None:
        try:
            if sys.platform.startswith('win'):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception:
            pass

    @Slot(int, QPoint)
    def on_grid_context_menu(self, global_index: int, global_pos) -> None:
        if not self.repo:
            return
        rec = self.store.record_at(global_index)
        if not rec:
            return
        menu = QMenu(self)
        act_copy = menu.addAction("Скопировать файл в…")
        chosen = menu.exec(global_pos)
        if chosen == act_copy:
            try:
                self._copy_file_of_index(global_index)
            except Exception:
                pass

    def _copy_file_of_index(self, index: int) -> None:
        if not self.repo:
            return
        rec = self.store.record_at(index)
        if not rec:
            return
        src = self.repo.abspath_for(rec['filename'], rec.get('status'))
        base = os.path.basename(src)
        dest_path, _ = QFileDialog.getSaveFileName(self, "Сохранить копию", os.path.join(self.repo.folder, base), "All Files (*)")
        if not dest_path:
            return
        if os.path.isdir(dest_path):
            dest_path = os.path.join(dest_path, base)
        if os.path.exists(dest_path):
            resp = QMessageBox.question(self, "Перезаписать файл?", f"Файл уже существует:\n{dest_path}\nПерезаписать?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return
        try:
            shutil.copy2(src, dest_path)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка копирования", f"Не удалось скопировать файл:\n{e}")

    @Slot(bool)
    def on_show_paths_toggled(self, show: bool) -> None:
        self._show_paths = show
        if self._is_grid_mode():
            self.grid_view.set_show_paths(show)
        else:
            rec = self.store.current_record()
            if show and self.repo and rec:
                path = self.repo.abspath_for(rec['filename'], rec.get('status'))
                rel = os.path.relpath(path, self.repo.folder)
                self.viewer.set_path_text(rel)
            else:
                self.viewer.set_path_text(None)

    @Slot(bool)
    def on_show_info_master_toggled(self, show: bool) -> None:
        self._show_info_master = show
        if show:
            # Sync child flags from sidebar current check states
            try:
                self._show_info_res = bool(self.top_menu.chk_info_res.isChecked())
                self._show_info_size = bool(self.top_menu.chk_info_size.isChecked())
                self._show_info_fmt = bool(self.top_menu.chk_info_fmt.isChecked())
            except Exception:
                pass
        else:
            # Hide all info badges when master is off
            self._show_info_res = False
            self._show_info_size = False
            self._show_info_fmt = False
        if self._is_grid_mode():
            self._refresh_grid_page()

    @Slot(bool)
    def on_show_info_res_toggled(self, show: bool) -> None:
        self._show_info_res = show
        if self._is_grid_mode():
            self._refresh_grid_page()

    @Slot(bool)
    def on_show_info_size_toggled(self, show: bool) -> None:
        self._show_info_size = show
        if self._is_grid_mode():
            self._refresh_grid_page()

    @Slot(bool)
    def on_show_info_fmt_toggled(self, show: bool) -> None:
        self._show_info_fmt = show
        if self._is_grid_mode():
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

    @Slot()
    def on_jump_to_first_unreviewed(self) -> None:
        # Find first record with status == 0 from the beginning
        records = self.store.records()
        target_index = -1
        for i, rec in enumerate(records):
            if int(rec.get('status', 0)) == 0:
                target_index = i
                break
        if target_index < 0:
            return
        # In grid mode, snap to the start of the page containing target_index
        if self._is_grid_mode():
            page_size = max(1, self.grid_rows * self.grid_cols)
            page_start = (target_index // page_size) * page_size
            if self.store.set_index(page_start):
                self._refresh_grid_page()
        else:
            if self.store.set_index(target_index):
                self._refresh_current_image()
                self._preload_neighbors()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # if event.key() == Qt.Key_Shift and not event.isAutoRepeat():
        #     # Toggle show paths
        #     self._show_paths = not self._show_paths
        #     self.sidebar.set_show_paths(self._show_paths)
        #     # Apply state
        #     if self._is_grid_mode():
        #         self.grid_view.set_show_paths(self._show_paths)
        #     else:
        #         if self._show_paths and self.repo:
        #             rec = self.store.current_record()
        #             if rec:
        #                 path = self.repo.abspath_for(rec['filename'], rec.get('status'))
        #                 rel = os.path.relpath(path, self.repo.folder)
        #                 self.viewer.set_path_text(rel)
        #         else:
        #             self.viewer.set_path_text(None)
        if event.key() in CONFIG.hotkeys.overlay_hold_keys:
            if not self._del_held:
                self._del_held = True
                self._layout_overlay()
                self._refresh_overlay_preview()
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
                        self._refresh_overlay_preview()
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
            self._hide_overlay_preview(clear_last=True)
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
        if base < 0:
            return None
        idx = base + r * self.grid_cols + c
        if idx >= len(self.store.records()):
            return None
        return idx

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
                    rel = os.path.relpath(target_path, self.repo.folder)
                    # Prepare footer: relative path • file size • WxH
                    size_text = ""
                    try:
                        size_bytes = os.path.getsize(target_path)
                        size_text = self._format_bytes(size_bytes)
                    except Exception:
                        size_text = "?"
                    wh_text = ""
                    try:
                        reader = QImageReader(target_path)
                        sz = reader.size()
                        if sz.isValid():
                            wh_text = f"{sz.width()}x{sz.height()}"
                    except Exception:
                        wh_text = ""
                    footer = f"{rel}"
                    if size_text:
                        footer += f" • {size_text}"
                    if wh_text:
                        footer += f" • {wh_text}"
                    self.overlay.set_footer(footer)
        else:
            rec = self.store.current_record()
            if rec:
                target_path = self.repo.abspath_for(rec['filename'], rec.get('status'))
                rel = os.path.relpath(target_path, self.repo.folder)
                size_text = ""
                try:
                    size_bytes = os.path.getsize(target_path)
                    size_text = self._format_bytes(size_bytes)
                except Exception:
                    size_text = "?"
                wh_text = ""
                try:
                    reader = QImageReader(target_path)
                    sz = reader.size()
                    if sz.isValid():
                        wh_text = f"{sz.width()}x{sz.height()}"
                except Exception:
                    wh_text = ""
                footer = f"{rel}"
                if size_text:
                    footer += f" • {size_text}"
                if wh_text:
                    footer += f" • {wh_text}"
                self.overlay.set_footer(footer)
        if not target_path:
            self._overlay_request_id += 1
            self.overlay.set_image(None)
            self.overlay.set_footer(None)
            return

        self._overlay_request_id += 1
        request_id = self._overlay_request_id

        def _set_overlay_image(image):
            if request_id != self._overlay_request_id:
                return
            self.overlay.set_image(image)

        self.preloader.request(target_path, (vw, vh), _set_overlay_image)

    def _format_bytes(self, num: int) -> str:
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        size = float(num)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == 'B':
                    return f"{int(size)} {unit}"
                else:
                    return f"{size:.1f} {unit}"
            size /= 1024
        return f"{num} B"

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
