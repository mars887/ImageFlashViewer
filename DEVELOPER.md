ImageFlashViewer — Developer Guide

If you change anything major in the code, don't forget to change this file.

Overview
- Purpose: A desktop tool to rapidly review/filter large image collections with keyboard-centric UX, including single and grid views, status marking, exports, and optional on‑disk grouping.
- Tech: Python 3, PySide6 (Qt), SQLite (stdlib), no network dependencies.

Repository Layout
- app.py — Entry point. Parses CLI flags, runs headless exports/deletions, or launches the GUI and optionally auto‑opens a folder (supports positional path argument).
- imageflash/__init__.py — Package docstring; explains package areas.
- imageflash/config.py — Central configuration. Styling, preloader limits, grid defaults, and hotkeys. Also holds badge thresholds/colors for the grid info overlays.
- imageflash/data/repo.py — SQLiteRepository. Owns .imageflash.sqlite schema, folder sync, status updates, grouping (moving files), exports, negative deletion, and path resolution.
- imageflash/services/scanner.py — Fast folder scan for supported extensions (flat or grouped subfolders: positive/unfiltered/negative).
- imageflash/services/preloader.py — Threaded image loader + in‑memory LRU cache. Request images by (path, size). Delivers QImage via Qt signals. Size is snapped internally to reduce cache fragmentation.
- imageflash/state/store.py — In‑memory list of images + current index. Emits signals for current item and stats. Provides next/prev, page navigation (grid), and status updates.
- imageflash/ui/main_window.py — Main UI composition and behavior. Connects sidebar, single view, grid view, overlay. Wires hotkeys, navigation, marking, grouping moves, preloading, and “info” badges.
- imageflash/ui/sidebar.py — Settings panel (folder chooser, stats, grid size sliders, path and info toggles, jump to first unreviewed).
- imageflash/ui/view_single.py — Single‑image viewer with optional bottom path bar that integrates the status strip.
- imageflash/ui/view_grid.py — Grid viewer. Renders tiles, preloads/rescales, draws per‑tile path/status bars and info badges (Res/Size/Fmt). Handles tile clicks.
- imageflash/ui/overlay.py — Full‑window spotlight overlay: dim background, centered image, footer with relative path, file size, and WxH.
- README.md — Quick start + CLI usage.
- requirements.txt — PySide6 runtime dependency.
- .gitignore — Standard Python ignores + app artifacts.

Launch, CLI & GUI
- Install: `pip install -r requirements.txt`
- Launch GUI (full‑screen by default):
  - `python app.py` — empty window, select a folder in sidebar
  - `python app.py "C:\\Photos"` — opens given folder (positional arg)
  - `python app.py --folder "C:\\Photos"` — same via flag
- CLI (headless) with folder required:
  - Export table: `python app.py "C:\\Photos" --export status --export_format csv|json`
  - Export list: `python app.py "C:\\Photos" --export positive|negative|unfiltered`
  - Delete negatives: `python app.py "C:\\Photos" --delete_negative`
- Grouping mode (affects GUI/CLI): `--group_images true|false` organizes files into positive/unfiltered/negative and moves on status change.

Data Model & Storage
- DB path: `<folder>/.imageflash.sqlite`.
- Table: images(id, filename UNIQUE, status [-1,0,1], reviewed_at TEXT).
- Sync: on folder selection, new files are inserted; missing files are removed and logged to `<folder>/deleted.csv`.
- Grouping: when enabled, files are moved between subfolders on status change; repo.abspath_for() resolves actual file path from DB filename.

State & Navigation
- ImageStore keeps an ordered list of dicts: {id, filename, status}. The store’s current index is the single‑view image and the top‑left item in grid view.
- Linear navigation: prev()/next().
- Paging (grid): page_indices(rows, cols), next_page(), prev_page(). The page start always aligns to multiples of page size.
- Stats signals: statsChanged(total, pos, neg, unreviewed) for sidebar.

UI Composition
- QSplitter: [sidebar | stacked viewer]. Stacked viewer switches between single and grid based on grid size sliders.
- Sidebar:
  - Folder field + native picker
  - Stats
  - Grid sliders: columns (X), rows (Y). Defaults in `CONFIG.grid_default_cols/rows`.
  - “Показывать пути” toggle — shows relative path bars in both views; integrates the status strip into the path bar.
  - “Информация” master toggle — reveals child toggles (Res, Size, Fmt):
    - Res: “X.YM” megapixels (color from `CONFIG.resolution_badges`), based on minimum of MP rank and min‑side rank.
    - Size: “NNNK” using KB thresholds from `CONFIG.size_badges`.
    - Fmt: uppercase file extension with gray badge color `CONFIG.format_badge_color`.
  - “К первому непроверенному” button — jumps to the first unreviewed image (snaps to page start in grid mode).

Grid View Details (view_grid.py)
- Tile sizing: computed from viewport and spacing (`CONFIG.grid_tile_spacing`).
- Image loading: requests images at tile size through the preloader; defers if tiles are not yet laid out, then re‑requests post‑layout.
- Painting: always scales the cached QImage to the current tile rect (KeepAspectRatio + Smooth) and clips to avoid bleed. This eliminates undersized/oversized first render.
- Interactions per tile:
  - LMB: toggle +1/0; RMB: toggle −1/0; MMB: open in external viewer.
  - Hover targeting (for overlay) via `index_at_point()`.
- Badges:
  - Drawn top‑right in right‑to‑left order (Res, Size, Fmt) with semi‑transparent background.
  - Colors are configurable in `config.py` and share a global alpha `CONFIG.resolution_badge_alpha`.

Single View Details (view_single.py)
- Scales one image to fit; draws a bottom status stripe or a path bar with status segment when paths are enabled.

Overlay (overlay.py)
- Hold overlay key(s) (see hotkeys) to display the image under the cursor (grid) or current image (single) with a dim background and margins. Footer shows: relative path • humanized file size • WxH (read via QImageReader).
- While holding overlay, pressing numpad digits selects the respective grid cell (789/456/123); mouse move cancels the override.

Hotkeys (config.py)
- `CONFIG.hotkeys` defines both QAction/QShortcut bindings (list of QKeySequence strings) and low‑level event keys (lists of Qt.Key enums). Multiple bindings per action are supported.
- Defaults (summarized; see config.py for details):
  - F11 — toggle fullscreen
  - Left/Right — prev/next (image or page)
  - Up/Down — mark positive/negative; grid marks only unreviewed in current set and advances to next set
  - ‘/’, ‘*’ — batch negative/positive (unreviewed, else all)
  - Enter/Return — next grid page
  - Space — affects the next grid page: mark unreviewed positive; if ‘+’ held mark all positive; if ‘−’ held mark all negative; then navigate to it
  - Delete (held) — overlay spotlight; with numpad digits selects a tile to preview
  - Numpad digits 789/456/123 — target grid cells; tap cycles 0→+1→−1→0, or use held modifier keys: ‘+’→+1, ‘−’→−1, ‘0’→0
  - Chord ‘0’ + ‘−’ — clear current page (set all to 0)

Configuration (config.py)
- Visuals: colors, stripe heights, spacing.
- Preloading: preloader_max_items (LRU size), preload_radius (neighbor prefetch in single view).
- Grid defaults: `grid_default_cols`, `grid_default_rows`.
- Hotkeys: see `Hotkeys` dataclass.
- Badge rules:
  - `resolution_badges`: list of (mp_threshold, min_side_threshold, hex_color). First/top tier uses strict ‘>’; others use ‘>=’. Effective color index is min(rank(mp), rank(min_side)).
  - `size_badges`: list of (kilobytes_threshold, hex_color) from high→low. First/top uses ‘>’; others use ‘>=’.
  - `resolution_badge_alpha`, `format_badge_color`.

Preloader (services/preloader.py)
- UI calls `preloader.request(path, (w, h), callback)` to enqueue loads. The loader reads the image and scales it to the requested size (KeepAspectRatio + Smooth). Results are cached using a size “snapping” function to avoid fragmentation.
- In grid painting we rescale cached QImages again to current tile size to guarantee exact fit.

SQLite Repository (data/repo.py)
- `init()` creates schema and optional grouping directories.
- `sync_with_folder(filenames)`: inserts new files, removes missing and logs to `deleted.csv`.
- `update_status(filename, status)`: persists status + timestamp.
- `export_status()` / `export_list_by_status()` produce CSV/JSON.
- `delete_negative()`: removes files (and records) with status −1, logs deletions.
- Grouping helpers: `enforce_grouping_for_all()`, `move_file_to_group()`, `abspath_for()`.

Signals & Event Flow (high‑level)
1) Folder selected → repo.init → scan → repo.sync → store.load_records → stacked view shown via `_apply_view_mode()`.
2) In grid: `_refresh_grid_page()` builds page items (paths, optional metadata) and calls grid.set_items(). Grid emits `requestRescale` on resize to drive preloading; tiles request images at tile size.
3) Marking: viewer/grid emits intents → store updates status (and emits stats) → repo persists → optional file move (grouping) → grid updates the one cell or advances page for batch flows.
4) Shortcuts are configured with ApplicationShortcut context to work regardless of focus.

Extending the App
- Add a new info badge: extend config for thresholds/colors as needed; extend main_window to attach required metadata; implement draw logic in view_grid.
- Add a new CLI command: extend argparse in app.py; use SQLiteRepository for data operations.
- Add file watching: integrate a watchdog thread and call `repo.sync_with_folder()` + `store.load_records()` when changes occur.
- Persist settings (future): use QSettings to store grid size, toggles, and hotkeys if needed.

Code Style & Notes
- Keep UI work on the main thread; image IO/scaling goes through preloader threads.
- Avoid expensive work inside paintEvent; we only scale QPixmaps.
- When modifying store signals, be careful to not over‑emit `currentChanged` for non‑current indices (prevents page re‑build jitter).
- Grid “current index” is the top‑left item; all page computations align to page size.