import sys
import argparse
from imageflash.ui.main_window import MainWindow
from imageflash.data.repo import SQLiteRepository
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication

# Developer Notes (app.py)
# - This is the application entrypoint. It parses CLI flags for export/delete
#   operations and, when none are provided, starts the Qt GUI.
# - CLI path: construct SQLiteRepository using --folder and perform export
#   (status or lists) or bulk deletion of negatives.
# - GUI path: creates QApplication, instantiates MainWindow, and shows it
#   fullscreen by default. The --group_images flag is passed through.
# - Extend here when adding additional headless commands or environment setup.


def _parse_bool(val: str) -> bool:
    v = str(val).strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def main():
    parser = argparse.ArgumentParser(description="ImageFlashViewer GUI and CLI")
    parser.add_argument("path", nargs="?", default=None, help="Folder with images and DB (positional)")
    parser.add_argument("--folder", type=str, help="Folder with images and DB", default=None)
    parser.add_argument("--export", type=str, choices=["status", "negative", "positive", "unfiltered"], help="Export mode", default=None)
    parser.add_argument("--export_format", type=str, choices=["json", "csv"], help="Export format", default="csv")
    parser.add_argument("--export_directory", type=str, help="Output directory (default: image folder)", default=None)
    parser.add_argument("--group_images", type=str, help="Group files into positive/unfiltered/negative and move on change (true/false)", default="false")
    parser.add_argument("--delete_negative", action="store_true", help="Delete all negative images")

    args = parser.parse_args()

    group_images = _parse_bool(args.group_images)
    folder_arg = args.folder or args.path

    # Headless CLI operations if export or delete flags provided
    if args.export or args.delete_negative:
        if not folder_arg:
            print("--folder is required for CLI operations", file=sys.stderr)
            sys.exit(2)
        repo = SQLiteRepository(folder_arg, group_images=group_images)
        repo.init()
        # When grouping is enabled, make sure structure exists and matches statuses
        if group_images:
            repo.enforce_grouping_for_all()

        if args.export:
            if args.export == "status":
                out = repo.export_status(args.export_directory, fmt=args.export_format)
                print(out)
                sys.exit(0)
            else:
                status_map = {"positive": 1, "negative": -1, "unfiltered": 0}
                out = repo.export_list_by_status(status_map[args.export], args.export_directory, fmt=args.export_format)
                print(out)
                sys.exit(0)

        if args.delete_negative:
            count = repo.delete_negative()
            print(count)
            sys.exit(0)

    # GUI mode
    QCoreApplication.setOrganizationName("ImageFlashViewer")
    QCoreApplication.setApplicationName("ImageFlashViewer")
    app = QApplication(sys.argv)

    window = MainWindow(group_images=group_images)
    # Start fullscreen by default
    window.showFullScreen()

    # If a folder path was supplied positionally or via --folder, open it
    if folder_arg:
        try:
            window.on_folder_selected(folder_arg)
        except Exception:
            pass

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
