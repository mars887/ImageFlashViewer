from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot, Qt
from PySide6.QtGui import QImage, QImageReader
from ..config import CONFIG

# Developer Notes (services/preloader.py)
# - Threaded image loading/caching. Uses QThreadPool + QRunnable workers and an
#   in-memory LRU keyed by (path, snapped_size). Call request(path, size, cb)
#   from the UI; callback will be invoked on the main thread via Qt signals.
# - _normalize_size snaps requested size to reduce cache fragmentation.
# - Cache size is controlled by CONFIG.preloader_max_items.


def _normalize_size(size: Tuple[int, int]) -> Tuple[int, int]:
    # Reduce cache fragmentation by snapping to 64px grid
    w, h = size
    snap = 16
    nw = max(snap, (w + snap - 1) // snap * snap)
    nh = max(snap, (h + snap - 1) // snap * snap)
    return nw, nh


class _WorkerSignals(QObject):
    loaded = Signal(str, int, tuple, QImage)  # path, version, size, image


class _SizeWorkerSignals(QObject):
    loaded = Signal(str, int, object)  # path, version, Optional[(w, h)]


class _ImageLoadWorker(QRunnable):
    def __init__(self, path: str, version: int, size: Tuple[int, int], signals: _WorkerSignals) -> None:
        super().__init__()
        self.path = path
        self.version = version
        self.size = size
        self.signals = signals

    @Slot()
    def run(self) -> None:  # type: ignore[override]
        try:
            img = QImage(self.path)
            if img.isNull():
                # Return a null image; UI can handle it
                self.signals.loaded.emit(self.path, self.version, self.size, QImage())
                return
            w, h = self.size
            scaled = img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # type: ignore[name-defined]
            self.signals.loaded.emit(self.path, self.version, self.size, scaled)
        except Exception:
            self.signals.loaded.emit(self.path, self.version, self.size, QImage())


class _ImageSizeWorker(QRunnable):
    def __init__(self, path: str, version: int, signals: _SizeWorkerSignals) -> None:
        super().__init__()
        self.path = path
        self.version = version
        self.signals = signals

    @Slot()
    def run(self) -> None:  # type: ignore[override]
        size: Optional[Tuple[int, int]] = None
        try:
            reader = QImageReader(self.path)
            image_size = reader.size()
            if image_size.isValid() and image_size.width() > 0 and image_size.height() > 0:
                size = (image_size.width(), image_size.height())
        except Exception:
            size = None
        self.signals.loaded.emit(self.path, self.version, size)


class ImagePreloader(QObject):
    """
    Simple threaded image preloader with in-memory LRU cache.
    """
    sizeLoaded = Signal(str)

    def __init__(self, max_items: int = None) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self.max_items = max_items if max_items is not None else CONFIG.preloader_max_items
        self.cache: "OrderedDict[Tuple[str, int, Tuple[int, int]], QImage]" = OrderedDict()
        self.signals = _WorkerSignals()
        self.signals.loaded.connect(self._on_loaded)
        self.size_signals = _SizeWorkerSignals()
        self.size_signals.loaded.connect(self._on_size_loaded)
        self._pending_callbacks: Dict[Tuple[str, int, Tuple[int, int]], List[Callable[[QImage], None]]] = {}
        self._inflight: Set[Tuple[str, int, Tuple[int, int]]] = set()
        self.size_cache: Dict[Tuple[str, int], Optional[Tuple[int, int]]] = {}
        self._size_inflight: Set[Tuple[str, int]] = set()
        self._path_versions: Dict[str, int] = {}

    def _path_version(self, path: str) -> int:
        return self._path_versions.get(path, 0)

    def _key(self, path: str, size: Tuple[int, int]) -> Tuple[str, int, Tuple[int, int]]:
        return path, self._path_version(path), _normalize_size(size)

    def _size_key(self, path: str) -> Tuple[str, int]:
        return path, self._path_version(path)

    def request(self, path: str, size: Tuple[int, int], callback: Optional[Callable[[QImage], None]] = None) -> None:
        key = self._key(path, size)
        if key in self.cache:
            img = self.cache[key]
            if callback:
                callback(img)
            # Move to MRU
            self.cache.move_to_end(key)
            return

        if callback:
            self._pending_callbacks.setdefault(key, []).append(callback)
        if key in self._inflight:
            return

        self._inflight.add(key)
        # Schedule worker
        worker = _ImageLoadWorker(path, key[1], key[2], self.signals)
        self.pool.start(worker)

    def request_size(self, path: str) -> Optional[Tuple[int, int]]:
        key = self._size_key(path)
        if key in self.size_cache:
            return self.size_cache[key]
        if key in self._size_inflight:
            return None
        self._size_inflight.add(key)
        self.pool.start(_ImageSizeWorker(path, key[1], self.size_signals))
        return None

    def get_cached_size(self, path: str) -> Tuple[bool, Optional[Tuple[int, int]]]:
        key = self._size_key(path)
        if key in self.size_cache:
            return True, self.size_cache[key]
        return False, None

    def prime_size(self, path: str, size: Optional[Tuple[int, int]]) -> None:
        self.size_cache[self._size_key(path)] = size

    def invalidate_path(self, path: str) -> None:
        self._path_versions[path] = self._path_version(path) + 1
        self.cache = OrderedDict((key, image) for key, image in self.cache.items() if key[0] != path)
        self._pending_callbacks = {key: callbacks for key, callbacks in self._pending_callbacks.items() if key[0] != path}
        self._inflight = {key for key in self._inflight if key[0] != path}
        self.size_cache = {key: size for key, size in self.size_cache.items() if key[0] != path}
        self._size_inflight = {key for key in self._size_inflight if key[0] != path}

    def clear_size_cache(self) -> None:
        self.size_cache.clear()
        self._size_inflight.clear()

    @Slot(str, int, tuple, QImage)
    def _on_loaded(self, path: str, version: int, size: Tuple[int, int], image: QImage) -> None:
        key = (path, version, size)
        self._inflight.discard(key)
        if version != self._path_version(path):
            self._pending_callbacks.pop(key, None)
            return
        # Insert into cache
        self.cache[key] = image
        self.cache.move_to_end(key)
        while len(self.cache) > self.max_items:
            self.cache.popitem(last=False)
        # Deliver any pending callbacks queued for this in-flight load.
        callbacks = self._pending_callbacks.pop(key, [])
        for cb in callbacks:
            cb(image)

    @Slot(str, int, object)
    def _on_size_loaded(self, path: str, version: int, size_obj) -> None:
        key = (path, version)
        self._size_inflight.discard(key)
        if version != self._path_version(path):
            return
        size = size_obj if isinstance(size_obj, tuple) and len(size_obj) == 2 else None
        self.size_cache[key] = size
        self.sizeLoaded.emit(path)
