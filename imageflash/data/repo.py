from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Iterable, List, Tuple, Dict, Optional

# Developer Notes (data/repo.py)
# - SQLiteRepository encapsulates DB access stored alongside images as
#   .imageflash.sqlite. It owns schema init, folder sync, status updates,
#   simple exports (CSV/JSON), grouping (moving files between subfolders),
#   and deletion of negatives with a deleted.csv log.
# - Filenames in DB are basenames only; use abspath_for() to resolve actual
#   paths, especially in grouping mode. All operations are per-call connections
#   (sqlite3.connect) with row_factory = Row.
# - Exports write to the image folder by default unless an explicit output
#   directory is provided.

class SQLiteRepository:
    def __init__(self, folder: str, group_images: bool = False) -> None:
        self.folder = os.path.abspath(folder)
        self.db_path = os.path.join(self.folder, ".imageflash.sqlite")
        self.group_images = group_images

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY,
                    filename TEXT UNIQUE NOT NULL,
                    status INTEGER NOT NULL DEFAULT 0,
                    reviewed_at TEXT
                );
                """
            )
            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_images_status ON images(status);
                """
            )
            conn.commit()

        if self.group_images:
            self._ensure_group_dirs()

    def sync_with_folder(self, filenames: Iterable[str]) -> List[str]:
        """
        Synchronize DB with provided filenames.
        - Insert new files at the end (autoincrement id order)
        - Remove missing files and log them to deleted.csv
        Returns list of removed filenames.
        """
        filenames = list(filenames)
        set_fs = set(filenames)

        removed: List[str] = []
        deleted_csv = os.path.join(self.folder, "deleted.csv")

        with self.connect() as conn:
            cur = conn.cursor()

            # Existing filenames in DB
            cur.execute("SELECT filename FROM images")
            in_db = {row[0] for row in cur.fetchall()}

            # New files
            new_files = [fn for fn in filenames if fn not in in_db]
            cur.executemany("INSERT OR IGNORE INTO images(filename) VALUES (?)", [(fn,) for fn in new_files])

            # Removed files
            missing = [fn for fn in in_db if fn not in set_fs]
            if missing:
                # Log to CSV
                try:
                    write_header = not os.path.exists(deleted_csv)
                    with open(deleted_csv, "a", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        if write_header:
                            w.writerow(["timestamp", "filename"])  # header
                        for fn in missing:
                            w.writerow([datetime.now().isoformat(timespec="seconds"), fn])
                except Exception:
                    # Logging failures shouldn't abort sync
                    pass
                cur.executemany("DELETE FROM images WHERE filename = ?", [(fn,) for fn in missing])

            conn.commit()
            removed = missing

        return removed

    def get_all_records(self) -> List[Dict]:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, filename, status FROM images ORDER BY id ASC")
            rows = cur.fetchall()
            return [
                {"id": row[0], "filename": row[1], "status": row[2]}
                for row in rows
            ]

    def update_status(self, filename: str, status: int) -> bool:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE images SET status = ?, reviewed_at = ? WHERE filename = ?",
                (status, datetime.now().isoformat(timespec="seconds"), filename),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_counts(self) -> Tuple[int, int, int, int]:
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM images")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM images WHERE status = 1")
            pos = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM images WHERE status = -1")
            neg = cur.fetchone()[0]
            unreviewed = total - pos - neg
            return total, pos, neg, unreviewed

    # Grouping helpers
    def _ensure_group_dirs(self) -> None:
        for d in ("positive", "unfiltered", "negative"):
            os.makedirs(os.path.join(self.folder, d), exist_ok=True)

    def _dir_for_status(self, status: int) -> str:
        return "positive" if status > 0 else ("negative" if status < 0 else "unfiltered")

    def abspath_for(self, filename: str, status: Optional[int] = None) -> str:
        if not self.group_images:
            return os.path.join(self.folder, filename)
        # Prefer path based on provided status
        if status is not None:
            candidate = os.path.join(self.folder, self._dir_for_status(status), filename)
            if os.path.exists(candidate):
                return candidate
        # Search in group dirs then top-level
        for d in ("positive", "unfiltered", "negative"):
            candidate = os.path.join(self.folder, d, filename)
            if os.path.exists(candidate):
                return candidate
        # Fallback to top-level
        return os.path.join(self.folder, filename)

    def enforce_grouping_for_all(self) -> None:
        if not self.group_images:
            return
        self._ensure_group_dirs()
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT filename, status FROM images")
            rows = cur.fetchall()
        for row in rows:
            fn, status = row[0], int(row[1])
            self._move_file_to_group(fn, status)

    def _move_file_to_group(self, filename: str, status: int) -> None:
        if not self.group_images:
            return
        self._ensure_group_dirs()
        src = self.abspath_for(filename)  # current location (search)
        dest = os.path.join(self.folder, self._dir_for_status(status), filename)
        # If src is already dest or src doesn't exist, skip
        if os.path.abspath(src) == os.path.abspath(dest):
            return
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(src):
                shutil.move(src, dest)
        except Exception:
            # Ignore move errors; keep DB consistent regardless
            pass

    def move_file_to_group(self, filename: str, status: int) -> None:
        self._move_file_to_group(filename, status)

    # Export helpers
    def export_status(self, out_dir: Optional[str], fmt: str = "csv") -> str:
        if not out_dir:
            out_dir = self.folder
        os.makedirs(out_dir, exist_ok=True)
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT filename, status FROM images ORDER BY id ASC")
            rows = [(row[0], int(row[1])) for row in cur.fetchall()]
        if fmt == "json":
            out_path = os.path.join(out_dir, "export_status.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump([{"imagePath": fn, "status": st} for fn, st in rows], f, ensure_ascii=False, indent=2)
            return out_path
        else:
            out_path = os.path.join(out_dir, "export_status.csv")
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["imagePath", "status"])
                w.writerows(rows)
            return out_path

    def export_list_by_status(self, status: int, out_dir: Optional[str], fmt: str = "csv") -> str:
        if not out_dir:
            out_dir = self.folder
        os.makedirs(out_dir, exist_ok=True)
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT filename FROM images WHERE status = ? ORDER BY id ASC", (status,))
            rows = [row[0] for row in cur.fetchall()]
        name = "positive" if status > 0 else ("negative" if status < 0 else "unfiltered")
        if fmt == "json":
            out_path = os.path.join(out_dir, f"{name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            return out_path
        else:
            out_path = os.path.join(out_dir, f"{name}.csv")
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["imagePath"])
                for fn in rows:
                    w.writerow([fn])
            return out_path

    def delete_negative(self) -> int:
        """Delete all files marked negative from disk and DB. Returns count of deletions."""
        # Collect negatives
        with self.connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT filename FROM images WHERE status = -1")
            negatives = [row[0] for row in cur.fetchall()]

        count = 0
        deleted_csv = os.path.join(self.folder, "deleted.csv")
        write_header = not os.path.exists(deleted_csv)
        try:
            f_csv = open(deleted_csv, "a", newline="", encoding="utf-8")
            writer = csv.writer(f_csv)
            if write_header:
                writer.writerow(["timestamp", "filename"])  # header
        except Exception:
            f_csv = None
            writer = None

        for fn in negatives:
            path = self.abspath_for(fn, -1) if self.group_images else self.abspath_for(fn)
            try:
                if os.path.exists(path):
                    os.remove(path)
                    count += 1
                    if writer:
                        writer.writerow([datetime.now().isoformat(timespec="seconds"), fn])
            except Exception:
                # skip failures
                pass

        if f_csv:
            try:
                f_csv.close()
            except Exception:
                pass

        # Remove from DB
        with self.connect() as conn:
            cur = conn.cursor()
            cur.executemany("DELETE FROM images WHERE filename = ?", [(fn,) for fn in negatives])
            conn.commit()

        return count
