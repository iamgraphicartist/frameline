"""Entry point."""
import os
import sys

from PySide6.QtCore import Qt, QEvent
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
            path = e.file()
            if self.window is not None:
                self.window.open_paths([path])
            else:
                self.pending.append(path)
            return True
        return super().event(e)


def main():
    if "--register" in sys.argv or "--unregister" in sys.argv:  # used by the installer
        from frameline import assoc
        if sys.platform == "win32":
            assoc.unregister_windows() if "--unregister" in sys.argv else assoc.register_windows()
        return
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Frameline.Player.1")
            ctypes.windll.winmm.timeBeginPeriod(1)  # 1 ms timer resolution for smooth playback
        except Exception:
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = App(sys.argv)
    app.setApplicationName("Frameline")
    app.setOrganizationName("Frameline")
    app.setStyle("Fusion")
    from frameline.window import MainWindow
    app.processEvents()
    files = [a for a in sys.argv[1:] if os.path.exists(a)] + app.pending
    w = MainWindow(files)
    app.window = w
    w.show()
    if os.environ.get("FRAMELINE_ABOUT"):  # screenshot the About box (build check)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog

        def grab_about():
            for d in app.topLevelWidgets():
                if isinstance(d, QDialog) and d.isVisible():
                    d.grab().save(os.environ["FRAMELINE_ABOUT"])
                    d.accept()
            app.quit()
        QTimer.singleShot(1500, lambda: (QTimer.singleShot(800, grab_about), w.show_about()))
    shot = os.environ.get("FRAMELINE_SELFTEST")
    if shot:  # used by the build to smoke-test the packaged exe
        from PySide6.QtCore import QTimer

        def finish():
            w.set_frame(30)
            QTimer.singleShot(1500, lambda: (w.grab().save(shot), w.project.__setattr__("dirty", False), app.quit()))
        QTimer.singleShot(2500, finish)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
