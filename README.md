ImageFlashViewer (Python, PySide6)

Quick start
- Create a virtual environment and install deps: `pip install -r requirements.txt`
- Run: `python app.py`

Usage
- Start in fullscreen. Toggle with `F11`.
- Select a folder in the left sidebar or paste a path and press Enter.
- Left/Right: navigate images. Up/Down: mark positive/negative.
- After marking, auto-advance to the next unreviewed image.

CLI
- Export (CSV by default):
  - `python app.py --folder \\path\\to\\images --export status --export_format csv|json --export_directory \\path\\to\\out`
  - `python app.py --folder \\path\\to\\images --export positive|negative|unfiltered --export_format csv|json --export_directory \\path\\to\\out`
- Delete negatives: `python app.py --folder \\path\\to\\images --delete_negative`
- Grouping mode (affects GUI and CLI): `--group_images true|false`
  - When true, files are organized into subfolders: `positive/`, `unfiltered/`, `negative/` under the selected folder, and moved on status change. New files are placed into `unfiltered/`.

Data
- Creates SQLite DB `.imageflash.sqlite` in the selected folder.
- Table `images` with columns: id, filename, status (-1,0,1), reviewed_at.
- On sync: new files are appended (higher id). Removed files are deleted from DB and appended to `deleted.csv` in the same folder.

Planned next
- Grid view (multi-image) on the same model.
- Adjustable preloading radius and cache size.
