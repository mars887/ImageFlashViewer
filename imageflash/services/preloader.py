from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot, Qt
from PySide6.QtGui import QImage
from ..config import CONFIG


def _normalize_size(size: Tuple[int, int]) -> Tuple[int, int]:
    # Reduce cache fragmentation by snapping to 64px grid
    w, h = size
    snap = 16
    nw = max(snap, (w + snap - 1) // snap * snap)
    nh = max(snap, (h + snap - 1) // snap * snap)
    return nw, nh


class _WorkerSignals(QObject):
    loaded = Signal(str, tuple, QImage)  # path, size, image


class _ImageLoadWorker(QRunnable):
    def __init__(self, path: str, size: Tuple[int, int], signals: _WorkerSignals) -> None:
        super().__init__()
        self.path = path
        self.size = size
        self.signals = signals

    @Slot()
    def run(self) -> None:  # type: ignore[override]
        try:
            img = QImage(self.path)
            if img.isNull():
                # Return a null image; UI can handle it
                self.signals.loaded.emit(self.path, self.size, QImage())
                return
            w, h = self.size
            scaled = img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # type: ignore[name-defined]
            self.signals.loaded.emit(self.path, self.size, scaled)
        except Exception:
            self.signals.loaded.emit(self.path, self.size, QImage())


class ImagePreloader(QObject):
    """
    Simple threaded image preloader with in-memory LRU cache.
    """

    def __init__(self, max_items: int = None) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self.max_items = max_items if max_items is not None else CONFIG.preloader_max_items
        self.cache: "OrderedDict[Tuple[str, Tuple[int, int]], QImage]" = OrderedDict()
        self.signals = _WorkerSignals()
        self.signals.loaded.connect(self._on_loaded)
        self._pending_callbacks: Dict[Tuple[str, Tuple[int, int]], Optional[Callable[[QImage], None]]] = {}

    def _key(self, path: str, size: Tuple[int, int]) -> Tuple[str, Tuple[int, int]]:
        return path, _normalize_size(size)

    def request(self, path: str, size: Tuple[int, int], callback: Optional[Callable[[QImage], None]] = None) -> None:
        key = self._key(path, size)
        if key in self.cache:
            img = self.cache[key]
            if callback:
                callback(img)
            # Move to MRU
            self.cache.move_to_end(key)
            return
        # Remember callback for delivery when loaded
        if callback:
            self._pending_callbacks[key] = callback
        # Schedule worker
        worker = _ImageLoadWorker(path, key[1], self.signals)
        self.pool.start(worker)

    @Slot(str, tuple, QImage)
    def _on_loaded(self, path: str, size: Tuple[int, int], image: QImage) -> None:
        key = (path, size)
        # Insert into cache
        self.cache[key] = image
        self.cache.move_to_end(key)
        while len(self.cache) > self.max_items:
            self.cache.popitem(last=False)
        # Deliver pending callback if any
        cb = self._pending_callbacks.pop(key, None)
        if cb:
            cb(image)
