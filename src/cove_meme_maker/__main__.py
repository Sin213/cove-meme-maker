import os
import sys

from PySide6.QtWidgets import QApplication

from .app import MainWindow


def main() -> int:
    # Inside a PyInstaller bundle, prepend the extracted data dir to PATH so
    # ``shutil.which('ffmpeg')`` finds the ffmpeg.exe we ship alongside the
    # app. A no-op when running from source.
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        os.environ["PATH"] = bundle_dir + os.pathsep + os.environ.get("PATH", "")
    app = QApplication(sys.argv)
    app.setApplicationName("Cove Meme Maker")
    app.setOrganizationName("Cove")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
