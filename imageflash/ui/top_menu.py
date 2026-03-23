from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QFileDialog,
    QMenu,
    QToolButton,
)

# Developer Notes (ui/top_menu.py)
# - Compact top control area that stays inside the left column only.
# - Hosts folder selection, database actions and info/path toggles that used to
#   live inside the sidebar. The main window wires these signals directly.


class TopMenuWidget(QWidget):
    folderSelected = Signal(str)
    showPathsToggled = Signal(bool)
    showInfoToggled = Signal(bool)
    showInfoResToggled = Signal(bool)
    showInfoSizeToggled = Signal(bool)
    showInfoFmtToggled = Signal(bool)
    exportStatusTo = Signal(int, str)  # status, out_dir
    deleteNegativeRequested = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.path_edit = QLineEdit()
        self.btn_browse = QPushButton("Выбрать папку...")
        self.btn_database = QToolButton()
        self.btn_database.setText("Database")
        self.btn_database.setPopupMode(QToolButton.InstantPopup)

        self.chk_show_paths = QCheckBox("Show paths")
        self.chk_show_info = QCheckBox("Show info")
        self.chk_info_res = QCheckBox("Res")
        self.chk_info_size = QCheckBox("Size")
        self.chk_info_fmt = QCheckBox("Fmt")

        self._build_ui()
        self._connect()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 0)
        layout.setSpacing(8)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        self.path_edit.setPlaceholderText("Путь к папке с изображениями...")
        path_row.addWidget(self.path_edit)
        path_row.addWidget(self.btn_browse)
        layout.addLayout(path_row)

        menu_row = QHBoxLayout()
        menu_row.setContentsMargins(0, 0, 0, 0)
        menu_row.setSpacing(12)
        menu_row.addWidget(self.btn_database)
        menu_row.addWidget(self.chk_show_paths)
        menu_row.addWidget(self.chk_show_info)
        menu_row.addStretch(1)
        layout.addLayout(menu_row)

        info_row = QHBoxLayout()
        info_row.setContentsMargins(16, 0, 0, 0)
        info_row.setSpacing(12)
        info_row.addWidget(self.chk_info_res)
        info_row.addWidget(self.chk_info_size)
        info_row.addWidget(self.chk_info_fmt)
        info_row.addStretch(1)
        layout.addLayout(info_row)

        self._set_info_children_visible(False)

    def _connect(self) -> None:
        self.btn_browse.clicked.connect(self._choose_folder)
        self.path_edit.returnPressed.connect(self._emit_folder)
        self.chk_show_paths.toggled.connect(self.showPathsToggled.emit)
        self.chk_show_info.toggled.connect(self._on_show_info_toggled)
        self.chk_info_res.toggled.connect(self.showInfoResToggled.emit)
        self.chk_info_size.toggled.connect(self.showInfoSizeToggled.emit)
        self.chk_info_fmt.toggled.connect(self.showInfoFmtToggled.emit)

        self.chk_info_res.setChecked(True)
        self._build_database_menu()

    def _build_database_menu(self) -> None:
        menu = QMenu(self)
        act_pos = menu.addAction("Export positive images to...")
        act_neg = menu.addAction("Export negative images to...")
        menu.addSeparator()
        act_del = menu.addAction("Delete negative images")

        act_pos.triggered.connect(lambda: self._on_export_click(+1))
        act_neg.triggered.connect(lambda: self._on_export_click(-1))
        act_del.triggered.connect(self.deleteNegativeRequested.emit)

        self.btn_database.setMenu(menu)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выбор папки с изображениями")
        if folder:
            self.path_edit.setText(folder)
            self.folderSelected.emit(folder)

    def _emit_folder(self) -> None:
        folder = self.path_edit.text().strip()
        if folder:
            self.folderSelected.emit(folder)

    def _set_info_children_visible(self, visible: bool) -> None:
        for widget in (self.chk_info_res, self.chk_info_size, self.chk_info_fmt):
            widget.setVisible(visible)

    def _on_show_info_toggled(self, show: bool) -> None:
        self._set_info_children_visible(show)
        self.showInfoToggled.emit(show)

    def _on_export_click(self, status: int) -> None:
        out_dir = QFileDialog.getExistingDirectory(self, "Choose export folder")
        if out_dir:
            self.exportStatusTo.emit(status, out_dir)

    def set_path(self, path: str) -> None:
        self.path_edit.setText(path)

    def set_show_paths(self, show: bool) -> None:
        self.chk_show_paths.setChecked(show)

    def set_show_info(self, show: bool) -> None:
        self.chk_show_info.setChecked(show)

    def set_info_res(self, show: bool) -> None:
        self.chk_info_res.setChecked(show)

    def set_info_size(self, show: bool) -> None:
        self.chk_info_size.setChecked(show)

    def set_info_fmt(self, show: bool) -> None:
        self.chk_info_fmt.setChecked(show)
