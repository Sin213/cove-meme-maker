import os
import sys


def main() -> int:
    # Inside a PyInstaller bundle, prepend the extracted data dir to PATH so
    # bundled binaries are found. A no-op when running from source.
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        os.environ["PATH"] = bundle_dir + os.pathsep + os.environ.get("PATH", "")

    # Tab-web env gate — must branch before any Qt import.
    if (
        os.environ.get("COVE_NEXUS") == "1"
        and os.environ.get("COVE_NEXUS_OPEN_MODE") == "tab-web"
        and os.environ.get("COVE_NEXUS_SOCKET")
        and os.environ.get("COVE_NEXUS_RUN_ID")
    ):
        from .tab_web import run as _run_tab_web
        return _run_tab_web(
            nexus_socket=os.environ["COVE_NEXUS_SOCKET"],
            run_id=os.environ["COVE_NEXUS_RUN_ID"],
        )

    from PySide6.QtWidgets import QApplication
    from . import theme
    from .app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Cove Meme Maker")
    app.setOrganizationName("Cove")
    theme.apply(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
