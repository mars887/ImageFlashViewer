import sys
import argparse
from imageflash.ui.main_window import MainWindow
from imageflash.data.repo import SQLiteRepository
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication


def _parse_bool(val: str) -> bool:
    v = str(val).strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def main():
    parser = argparse.ArgumentParser(description="ImageFlashViewer GUI and CLI")
    parser.add_argument("--folder", type=str, help="Folder with images and DB", default=None)
    parser.add_argument("--export", type=str, choices=["status", "negative", "positive", "unfiltered"], help="Export mode", default=None)
    parser.add_argument("--export_format", type=str, choices=["json", "csv"], help="Export format", default="csv")
    parser.add_argument("--export_directory", type=str, help="Output directory (default: image folder)", default=None)
    parser.add_argument("--group_images", type=str, help="Group files into positive/unfiltered/negative and move on change (true/false)", default="false")
    parser.add_argument("--delete_negaive", action="store_true", help="Delete all negative images (alias)")
    parser.add_argument("--delete_negative", action="store_true", help="Delete all negative images")

    args = parser.parse_args()

    group_images = _parse_bool(args.group_images)

    # Headless CLI operations if export or delete flags provided
    if args.export or args.delete_negative or args.delete_negaive:
        if not args.folder:
            print("--folder is required for CLI operations", file=sys.stderr)
            sys.exit(2)
        repo = SQLiteRepository(args.folder, group_images=group_images)
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

        if args.delete_negative or args.delete_negaive:
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
