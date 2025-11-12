from __future__ import annotations

from dataclasses import dataclass, field
from PySide6.QtCore import Qt

# Developer Notes (config.py)
# - Central configuration for the app. Includes visual styling, preloader
#   settings and the Hotkeys dataclass used by the UI for bindings.
# - QAction/QShortcut bindings are configured as QKeySequence strings, while
#   low-level key handling (event.key()) uses Qt.Key enums.
# - Adjust values here to tweak cache sizes, preload radius, colors and keymaps.

@dataclass
class Hotkeys:
    # QAction/QShortcut bindings (QKeySequence strings). Multiple allowed per action.
    toggle_fullscreen: list[str] = field(default_factory=lambda: ["F11"], metadata={"desc": "Toggle full screen view."})
    prev: list[str] = field(default_factory=lambda: ["Left"], metadata={"desc": "Previous image or previous grid page."})
    next: list[str] = field(default_factory=lambda: ["Right"], metadata={"desc": "Next image or next grid page."})
    mark_positive: list[str] = field(default_factory=lambda: ["Up"], metadata={"desc": "Mark current image positive; in grid mode, mark unreviewed positive on page."})
    mark_negative: list[str] = field(default_factory=lambda: ["Down"], metadata={"desc": "Mark current image negative; in grid mode, mark unreviewed negative on page."})
    grid_mark_negative_batch: list[str] = field(default_factory=lambda: ["/"], metadata={"desc": "Batch negative: mark unreviewed (or all) on page negative."})
    grid_mark_positive_batch: list[str] = field(default_factory=lambda: ["*"], metadata={"desc": "Batch positive: mark unreviewed (or all) on page positive."})
    grid_next_page: list[str] = field(default_factory=lambda: ["Return", "Enter"], metadata={"desc": "Advance grid to next page."})
    grid_prefill_next_positive: list[str] = field(default_factory=lambda: ["Space"], metadata={"desc": "On grid: Space marks unreviewed cells positive; if '+' held, mark all positive; if '-' held, mark all negative."})

    # event.key() comparisons (Qt key enums). Multiple allowed per action.
    overlay_hold_keys: list[int] = field(default_factory=lambda: [Qt.Key_Delete, Qt.Key_Period, Qt.Key_Comma], metadata={"desc": "While held, show spotlight overlay."})
    sign_plus_keys: list[int] = field(default_factory=lambda: [Qt.Key_Plus], metadata={"desc": "When held with digit, set cell to positive."})
    sign_minus_keys: list[int] = field(default_factory=lambda: [Qt.Key_Minus], metadata={"desc": "When held with digit, set cell to negative."})
    sign_clear_keys: list[int] = field(default_factory=lambda: [Qt.Key_0, Qt.Key_Insert], metadata={"desc": "When held with digit, clear cell (status 0)."})
    grid_digit_keys: list[int] = field(default_factory=lambda: [
        Qt.Key_1, Qt.Key_2, Qt.Key_3,
        Qt.Key_4, Qt.Key_5, Qt.Key_6,
        Qt.Key_7, Qt.Key_8, Qt.Key_9,
    ], metadata={"desc": "Digit keys mapping to grid cells (789/456/123)."})


@dataclass
class Config:
    # Caching / preloading
    preloader_max_items: int = 400
    preload_radius: int = 30

    # UI styling
    background_color: tuple[int, int, int] = (18, 18, 18)
    tile_background_color: tuple[int, int, int] = (28, 28, 28)
    border_color: tuple[int, int, int] = (60, 60, 60)
    stripe_positive_color: tuple[int, int, int, int] = (0, 200, 100, 160)
    stripe_negative_color: tuple[int, int, int, int] = (220, 60, 60, 160)

    # Dimensions
    single_status_stripe_height: int = 10
    grid_status_stripe_height: int = 8
    grid_tile_spacing: int = 3
    # Default grid size
    grid_default_cols: int = 3
    grid_default_rows: int = 2

    # Overlay
    overlay_margin: int = 32
    overlay_bg_alpha: int = 180

    # Hotkeys
    hotkeys: Hotkeys = field(default_factory=Hotkeys)

    # Resolution badge thresholds and colors (mp_threshold, ms_threshold, hex_color)
    # Ordered from highest to lowest quality; used in grid tile badge coloring.
    resolution_badges: list[tuple[float, int, str]] = field(
        default_factory=lambda: [
            (32.0, 4000, "#FF33FF"),  # pink
            (8.4, 2050, "#7777FF"),   # blue
            (1.6, 1100, "#55FF55"),   # green
            (0.7, 600, "#FFFF33"),    # yellow
            (0.0, 0, "#FF7777"),      # red
        ]
    )
    resolution_badge_alpha: int = 170
    # File size badge thresholds (KB) and colors (hex)
    size_badges: list[tuple[int, str]] = field(
        default_factory=lambda: [
            (4000, "#7777FF"),  # >=4MB ultra
            (800, "#55FF55"),  # >=0.8MB good
            (300, "#FFFF11"),   # >=300KB medium
            (150, "#FF8888"),   # >=150KB low
            (0, "#FF1111"),     # <200KB very low
        ]
    )
    format_badge_color: str = "#B0B0B0"


CONFIG = Config()
