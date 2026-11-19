"""Stillframe entry point."""
import os
import sys

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication


class App(QApplication):
    """Receives files opened from Finder / the Dock on macOS (they don't arrive as argv)."""

    def __init__(self, argv):
        super().__init__(argv)
        self.window = None
        self.pending = []

    def event(self, e):
        if e.type() == QEvent.Type.FileOpen:
            if self.window is not None:
                self.window.open_paths([e.file()])
            else:
                self.pending.append(e.file())
            return True
        return super().event(e)


def main():
    if "--register" in sys.argv or "--unregister" in sys.argv:  # used by the installer
        if sys.platform == "win32":
            from stillframe.window import STILLFRAME_ASSOC
            STILLFRAME_ASSOC.unregister_windows() if "--unregister" in sys.argv else STILLFRAME_ASSOC.register_windows()
        return
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Stillframe.Viewer.1")
        except Exception:
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = App(sys.argv)
    app.setApplicationName("Stillframe")
    app.setOrganizationName("Stillframe")
    app.setStyle("Fusion")
    from stillframe.window import MainWindow
    app.processEvents()
    files = [a for a in sys.argv[1:] if os.path.exists(a)] + app.pending
    w = MainWindow(files)
    app.window = w
    w.show()
    shot = os.environ.get("STILLFRAME_SELFTEST")
    if shot:  # used by the build to smoke-test the packaged exe
        def finish():
            w.grab().save(shot)
            app.quit()
        QTimer.singleShot(3000, finish)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
