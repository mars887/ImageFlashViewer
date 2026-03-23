from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QSlider,
)

from ..config import CONFIG

# Developer Notes (ui/sidebar.py)
# - Left-hand sidebar with persistent review controls only:
#   * review statistics
#   * grid size sliders
#   * jump-to-first-unreviewed button
# - Folder/database/info controls live in the top menu widget above the sidebar.


class SideBar(QWidget):
    gridSizeChanged = Signal(int, int)  # cols, rows
    jumpToFirstUnreviewed = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.lbl_total = QLabel("Всего: 0")
        self.lbl_pos = QLabel("Положительных: 0")
        self.lbl_neg = QLabel("Отрицательных: 0")
        self.lbl_unreviewed = QLabel("Непроверенных: 0")

        self.grid_cols_slider = QSlider(Qt.Horizontal)
        self.grid_cols_slider.setRange(1, 3)
        self.grid_cols_slider.setValue(CONFIG.grid_default_cols)
        self.grid_cols_label = QLabel(f"Колонки: {CONFIG.grid_default_cols}")

        self.grid_rows_slider = QSlider(Qt.Horizontal)
        self.grid_rows_slider.setRange(1, 3)
        self.grid_rows_slider.setValue(CONFIG.grid_default_rows)
        self.grid_rows_label = QLabel(f"Строки: {CONFIG.grid_default_rows}")

        self.btn_jump_first = QPushButton("К первому непроверенному")

        self._build_ui()
        self._connect()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        layout.addWidget(self.lbl_total)
        layout.addWidget(self.lbl_pos)
        layout.addWidget(self.lbl_neg)
        layout.addWidget(self.lbl_unreviewed)

        layout.addSpacing(8)
        layout.addWidget(self.grid_cols_label)
        layout.addWidget(self.grid_cols_slider)
        layout.addWidget(self.grid_rows_label)
        layout.addWidget(self.grid_rows_slider)
        layout.addStretch(1)
        layout.addWidget(self.btn_jump_first)

        self.setMinimumWidth(360)

    def _connect(self) -> None:
        self.grid_cols_slider.valueChanged.connect(self._grid_value_changed)
        self.grid_rows_slider.valueChanged.connect(self._grid_value_changed)
        self.btn_jump_first.clicked.connect(self.jumpToFirstUnreviewed.emit)

    def update_stats(self, total: int, pos: int, neg: int, unreviewed: int) -> None:
        self.lbl_total.setText(f"Всего: {total}")
        self.lbl_pos.setText(f"Положительных: {pos}")
        self.lbl_neg.setText(f"Отрицательных: {neg}")
        self.lbl_unreviewed.setText(f"Непроверенных: {unreviewed}")

    def _grid_value_changed(self, *_args) -> None:
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
