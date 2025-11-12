from __future__ import annotations

import os
from typing import Iterable, List


SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

# Developer Notes (services/scanner.py)
# - Scans a single folder for supported image extensions. In grouped mode it
#   also scans positive/unfiltered/negative subfolders and top-level images.
# - Returns basenames only (no directories), sorted and de-duplicated.
# - Keep SUPPORTED_EXT in sync with formats you want to allow.


def is_image_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in SUPPORTED_EXT


def scan_images(folder: str, grouped: bool = False) -> List[str]:
    """
    Scan only top-level files in folder for supported image extensions.
    Store just the base filenames (no subdirectories) as per the spec.
    """
    entries = []
    try:
        if grouped:
            dirs = [os.path.join(folder, d) for d in ("positive", "unfiltered", "negative")]
            for d in dirs:
                if not os.path.isdir(d):
                    continue
                for name in os.listdir(d):
                    abspath = os.path.join(d, name)
                    if os.path.isfile(abspath) and is_image_file(name):
                        entries.append(name)
            # Also include any top-level images (will be moved to unfiltered later)
            for name in os.listdir(folder):
                abspath = os.path.join(folder, name)
                if os.path.isfile(abspath) and is_image_file(name):
                    entries.append(name)
        else:
            for name in os.listdir(folder):
                abspath = os.path.join(folder, name)
                if os.path.isfile(abspath) and is_image_file(name):
                    entries.append(name)
    except FileNotFoundError:
        return []
    # Sort by name for determinism on first import; insertion order becomes id
    entries = sorted(list(dict.fromkeys(entries)))
    return entries
