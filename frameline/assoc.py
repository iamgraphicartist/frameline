"""File associations shared by Frameline and Stillframe.

Windows does not allow apps to silently make themselves the default (the choice is hash-protected), so we
register each app's capabilities per user and send the person to Settings or the Open-with picker to confirm.
"""
import os
import subprocess
import sys

EXPLORER_EXTS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
TOASTS = r"Software\Microsoft\Windows\CurrentVersion\ApplicationAssociationToasts"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Association:
    def __init__(self, app_name, progid, exe_name, exts, description, type_name, owned=(), run_script="run.py",
                 mac_hint="", linux_mimes=()):
        self.app_name, self.progid, self.exe_name = app_name, progid, exe_name
        self.exts, self.owned = tuple(exts), tuple(owned)
        self.description, self.type_name = description, type_name
        self.run_script, self.mac_hint, self.linux_mimes = run_script, mac_hint, linux_mimes

    def _command(self):
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" "%1"', f"{sys.executable},0"
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        return f'"{pyw}" "{os.path.join(_ROOT, self.run_script)}" "%1"', f"{pyw},0"

    def register_windows(self):
        """Per-user (HKCU): ProgID, Open-with lists, Default Apps capabilities and the Settings picker."""
        import winreg
        cmd, icon = self._command()
        C = winreg.HKEY_CURRENT_USER

        def setv(path, name, value, kind=winreg.REG_SZ):
            with winreg.CreateKeyEx(C, path, 0, winreg.KEY_WRITE) as k:
                winreg.SetValueEx(k, name, 0, kind, value)

        base = rf"Software\Classes\{self.progid}"
        setv(base, "", self.type_name)
        setv(base, "FriendlyTypeName", self.type_name)
        setv(base + r"\DefaultIcon", "", icon)
        setv(base + r"\shell\open\command", "", cmd)
        setv(base + r"\Application", "ApplicationName", self.app_name)
        setv(base + r"\Application", "ApplicationIcon", icon)
        setv(base + r"\Application", "ApplicationCompany", "Miguel Rato")
        app = rf"Software\Classes\Applications\{self.exe_name}"
        setv(app, "FriendlyAppName", self.app_name)
        setv(app + r"\shell\open\command", "", cmd)
        caps = rf"Software\{self.app_name}\Capabilities"
        setv(caps, "ApplicationName", self.app_name)
        setv(caps, "ApplicationDescription", self.description)
        setv(caps, "ApplicationIcon", icon)
        for e in self.exts + self.owned:
            setv(rf"Software\Classes\{e}\OpenWithProgids", self.progid, "")
            setv(app + r"\SupportedTypes", e, "")
            setv(caps + r"\FileAssociations", e, self.progid)
            # Explorer's per-user list feeds the "Open with" picker
            setv(EXPLORER_EXTS + rf"\{e}\OpenWithProgids", self.progid, b"", winreg.REG_NONE)
            # the Settings picker only lists handlers Windows has already "announced" for the type
            for name in (f"{self.progid}_{e}", rf"Applications\{self.exe_name}_{e}"):
                setv(TOASTS, name, 0, winreg.REG_DWORD)
        setv(r"Software\RegisteredApplications", self.app_name, caps)
        for e in self.owned:   # our own document types: claim them outright
            setv(rf"Software\Classes\{e}", "", self.progid)
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
        except Exception:
            pass

    def unregister_windows(self):
        import winreg
        C = winreg.HKEY_CURRENT_USER

        def delete_tree(path):
            try:
                with winreg.OpenKey(C, path, 0, winreg.KEY_ALL_ACCESS) as k:
                    while True:
                        try:
                            sub = winreg.EnumKey(k, 0)
                        except OSError:
                            break
                        delete_tree(path + "\\" + sub)
                winreg.DeleteKey(C, path)
            except OSError:
                pass

        def delv(path, name):
            try:
                with winreg.OpenKey(C, path, 0, winreg.KEY_WRITE) as k:
                    winreg.DeleteValue(k, name)
            except OSError:
                pass

        for e in self.exts + self.owned:
            delv(rf"Software\Classes\{e}\OpenWithProgids", self.progid)
            delv(EXPLORER_EXTS + rf"\{e}\OpenWithProgids", self.progid)
            delv(TOASTS, f"{self.progid}_{e}")
            delv(TOASTS, rf"Applications\{self.exe_name}_{e}")
        delv(r"Software\RegisteredApplications", self.app_name)
        for path in (rf"Software\Classes\{self.progid}", rf"Software\Classes\Applications\{self.exe_name}",
                     rf"Software\{self.app_name}") + tuple(rf"Software\Classes\{e}" for e in self.owned):
            delete_tree(path)

    def exe_path(self):
        return sys.executable if getattr(sys, "frozen", False) else os.path.join(_ROOT, self.run_script)

    def make_default(self):
        """Register, then return instructions (and copy the app's path) for confirming it as the default."""
        if sys.platform == "win32":
            self.register_windows()
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.clipboard().setText(self.exe_path())
            except Exception:
                pass
            return (f"{self.app_name} is registered with Windows. To make it the default:\n\n"
                    f"1. Right-click a file and choose Open with → Choose another app.\n"
                    f"2. Pick {self.app_name}. If it isn't listed, click “Choose an app on your PC” and paste "
                    f"its location (already copied to your clipboard).\n"
                    f"3. Click Always.\n\nRepeat once for each file type you want it to open.")
        if sys.platform == "darwin":
            return self.mac_hint
        try:
            subprocess.run(["xdg-mime", "default", f"{self.app_name.lower()}.desktop", *self.linux_mimes], check=False)
        except Exception:
            pass
        return None


FRAMELINE = Association(
    "Frameline", "Frameline.Media", "Frameline.exe",
    exts=(".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mxf", ".mpg", ".mpeg", ".wmv", ".flv", ".ts", ".mts",
          ".m2ts", ".3gp", ".ogv", ".exr", ".dpx", ".tif", ".tiff"),
    owned=(".flsession",), description="Frame-accurate media player and review tool", type_name="Frameline media",
    run_script="run.py",
    mac_hint="To open all videos with Frameline: in Finder, select a video, press ⌘I, choose Frameline under "
             "“Open with”, then click “Change All…”. Repeat once per file type (.mp4, .mov, …).",
    linux_mimes=("video/mp4", "video/quicktime", "video/x-matroska", "video/webm"))

# backwards-compatible module API used by Frameline
VIDEO_EXTS = FRAMELINE.exts
PROGID = FRAMELINE.progid
APP_NAME = FRAMELINE.app_name
register_windows = FRAMELINE.register_windows
unregister_windows = FRAMELINE.unregister_windows
make_default = FRAMELINE.make_default
