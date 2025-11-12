from __future__ import annotations

import os
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QFileDialog,
    QSlider,
    QCheckBox,
)

# Developer Notes (ui/sidebar.py)
# - Left-hand settings panel. Emits:
#   * folderSelected(str) when a folder is chosen/entered
#   * gridSizeChanged(cols, rows) for grid dimensions (1..3)
#   * showPathsToggled(bool) to toggle per-image path labels
#   * jumpToFirstUnreviewed() to navigate to first unreviewed item
# - Update labels via update_stats(); use set_grid_size() and set_show_paths()
#   to reflect external state changes.


class SideBar(QWidget):
    folderSelected = Signal(str)
    gridSizeChanged = Signal(int, int)  # cols, rows
    showPathsToggled = Signal(bool)
    jumpToFirstUnreviewed = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.path_edit = QLineEdit()
        self.btn_browse = QPushButton("Выбрать папку…")

        self.lbl_total = QLabel("Всего: 0")
        self.lbl_pos = QLabel("Положительных: 0")
        self.lbl_neg = QLabel("Отрицательных: 0")
        self.lbl_unreviewed = QLabel("Непроверенных: 0")

        # Grid controls
        self.grid_cols_slider = QSlider(Qt.Horizontal)
        self.grid_cols_slider.setRange(1, 3)
        self.grid_cols_slider.setValue(1)
        self.grid_cols_label = QLabel("Колонки: 1")

        self.grid_rows_slider = QSlider(Qt.Horizontal)
        self.grid_rows_slider.setRange(1, 3)
        self.grid_rows_slider.setValue(1)
        self.grid_rows_label = QLabel("Строки: 1")

        self.chk_show_paths = QCheckBox("Показывать пути")
        self.btn_jump_first = QPushButton("К первому непроверенному")

        self._build_ui()
        self._connect()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Path row
        row = QHBoxLayout()
        self.path_edit.setPlaceholderText("Путь к папке с изображениями…")
        row.addWidget(self.path_edit)
        row.addWidget(self.btn_browse)
        layout.addLayout(row)

        layout.addSpacing(12)
        layout.addWidget(self.lbl_total)
        layout.addWidget(self.lbl_pos)
        layout.addWidget(self.lbl_neg)
        layout.addWidget(self.lbl_unreviewed)

        # Grid sliders
        layout.addSpacing(12)
        layout.addWidget(self.grid_cols_label)
        layout.addWidget(self.grid_cols_slider)
        layout.addWidget(self.grid_rows_label)
        layout.addWidget(self.grid_rows_slider)
        layout.addSpacing(12)
        layout.addWidget(self.chk_show_paths)
        layout.addStretch(1)
        layout.addWidget(self.btn_jump_first)

        self.setMinimumWidth(360)

    def _connect(self) -> None:
        self.btn_browse.clicked.connect(self._choose_folder)
        self.path_edit.returnPressed.connect(self._emit_folder)
        self.grid_cols_slider.valueChanged.connect(self._grid_value_changed)
        self.grid_rows_slider.valueChanged.connect(self._grid_value_changed)
        self.chk_show_paths.toggled.connect(self.showPathsToggled.emit)
        self.btn_jump_first.clicked.connect(self.jumpToFirstUnreviewed.emit)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выбор папки с изображениями")
        if folder:
            self.path_edit.setText(folder)
            self.folderSelected.emit(folder)

    def _emit_folder(self) -> None:
        folder = self.path_edit.text().strip()
        if folder:
            self.folderSelected.emit(folder)

    def update_stats(self, total: int, pos: int, neg: int, unreviewed: int) -> None:
        self.lbl_total.setText(f"Всего: {total}")
        self.lbl_pos.setText(f"Положительных: {pos}")
        self.lbl_neg.setText(f"Отрицательных: {neg}")
        self.lbl_unreviewed.setText(f"Непроверенных: {unreviewed}")

    def _grid_value_changed(self, *_):
        cols = self.grid_cols_slider.value()
        rows = self.grid_rows_slider.value()
        self.grid_cols_label.setText(f"Колонки: {cols}")
        self.grid_rows_label.setText(f"Строки: {rows}")
        self.gridSizeChanged.emit(cols, rows)

    def set_grid_size(self, cols: int, rows: int) -> None:
        self.grid_cols_slider.setValue(cols)
        self.grid_rows_slider.setValue(rows)
        self.grid_cols_label.setText(f"Колонки: {cols}")
        self.grid_rows_label.setText(f"Строки: {rows}")

    def set_show_paths(self, show: bool) -> None:
        self.chk_show_paths.setChecked(show)
