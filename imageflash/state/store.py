from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

# Developer Notes (state/store.py)
# - ImageStore holds in-memory records loaded from the repository and emits
#   signals: currentChanged(index, status) and statsChanged(total, pos, neg, unreviewed).
# - Provides linear navigation and page-based navigation helpers for grid mode.
# - mark_status()/mark_status_at() persist via the repo and update local state.
# - The current index is treated as the single-view image and top-left of grid.


class ImageStore(QObject):
    currentChanged = Signal(int, int)  # index, status
    statsChanged = Signal(int, int, int, int)  # total, pos, neg, unreviewed

    def __init__(self) -> None:
        super().__init__()
        self._records: List[Dict] = []
        self._index: int = -1

    # Records and stats
    def load_records(self, records: List[Dict]) -> None:
        self._records = list(records)
        self._index = 0 if self._records else -1
        self._emit_stats()
        self._emit_current()

    def records(self) -> List[Dict]:
        return self._records

    def record_at(self, index: int) -> Optional[Dict]:
        if 0 <= index < len(self._records):
            return self._records[index]
        return None

    def current_record(self) -> Optional[Dict]:
        return self.record_at(self._index)

    def index(self) -> int:
        return self._index

    # Navigation
    def set_index(self, new_index: int) -> bool:
        if 0 <= new_index < len(self._records) and new_index != self._index:
            self._index = new_index
            self._emit_current()
            return True
        return False

    def prev(self) -> bool:
        if self._index > 0:
            self._index -= 1
            self._emit_current()
            return True
        return False

    def next(self) -> bool:
        if self._index < len(self._records) - 1:
            self._index += 1
            self._emit_current()
            return True
        return False

    # Paging for grid mode
    def page_indices(self, rows: int, cols: int) -> List[int]:
        if self._index < 0 or not self._records:
            return []
        size = max(1, rows) * max(1, cols)
        end = min(len(self._records), self._index + size)
        return list(range(self._index, end))

    def current_page_records(self, rows: int, cols: int) -> List[Dict]:
        return [self._records[i] for i in self.page_indices(rows, cols)]

    def next_page(self, rows: int, cols: int) -> bool:
        size = max(1, rows) * max(1, cols)
        if not self._records:
            return False
        last_start = max(0, len(self._records) - size)
        new_index = self._index + size
        if new_index > last_start:
            new_index = last_start
        if new_index != self._index:
            self._index = new_index
            self._emit_current()
            return True
        return False

    def prev_page(self, rows: int, cols: int) -> bool:
        if not self._records or self._index < 0:
            return False
        size = max(1, rows) * max(1, cols)
        new_index = max(0, self._index - size)
        if new_index != self._index:
            self._index = new_index
            self._emit_current()
            return True
        return False

    def neighbor_indices(self, radius: int) -> List[int]:
        if self._index < 0:
            return []
        start = max(0, self._index - radius)
        end = min(len(self._records), self._index + radius + 1)
        return [i for i in range(start, end) if i != self._index]

    # Status and stats
    def _emit_current(self) -> None:
        rec = self.current_record()
        status = rec.get("status", 0) if rec else 0
        self.currentChanged.emit(self._index, status)

    def _emit_stats(self) -> None:
        total = len(self._records)
        pos = sum(1 for r in self._records if r.get("status") == 1)
        neg = sum(1 for r in self._records if r.get("status") == -1)
        unreviewed = total - pos - neg
        self.statsChanged.emit(total, pos, neg, unreviewed)

    def mark_status(self, status: int, repo) -> bool:
        rec = self.current_record()
        if not rec:
            return False
        if rec.get("status") == status:
            return False
        ok = repo.update_status(rec["filename"], status)
        if ok:
            rec["status"] = status
            self._emit_current()
            self._emit_stats()
        return ok

    def mark_status_at(self, index: int, status: int, repo) -> bool:
        if not (0 <= index < len(self._records)):
            return False
        rec = self._records[index]
        if rec.get("status") == status:
            return False
        ok = repo.update_status(rec["filename"], status)
        if ok:
            rec["status"] = status
            # Update signals as needed
            if index == self._index:
                # Only emit currentChanged when the top-left/current index itself changed
                self._emit_current()
            self._emit_stats()
        return ok

    def goto_next_unreviewed(self) -> bool:
        i = self._index + 1
        while i < len(self._records):
            if self._records[i].get("status") == 0:
                return self.set_index(i)
            i += 1
        return False
