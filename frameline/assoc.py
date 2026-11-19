"""File associations: register Frameline as a player for video/image files and open the OS default-apps page.

Windows does not allow apps to silently make themselves the default (the choice is hash-protected), so we
register Frameline's capabilities and send the user to Settings, where one click sets it for every type.
"""
import os
import subprocess
import sys

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mxf", ".mpg", ".mpeg", ".wmv", ".flv",
              ".ts", ".mts", ".m2ts", ".3gp", ".ogv")
IMAGE_EXTS = (".exr", ".dpx", ".tif", ".tiff")
SESSION_EXT = ".flsession"
PROGID = "Frameline.Media"
APP_NAME = "Frameline"
EXPLORER_EXTS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
TOASTS = r"Software\Microsoft\Windows\CurrentVersion\ApplicationAssociationToasts"


def _command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"', f"{sys.executable},0"
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    run = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.py")
    return f'"{pyw}" "{run}" "%1"', f"{pyw},0"


def register_windows():
    """Per-user registration (HKCU): ProgID, Open-with entries and Default Apps capabilities."""
    import winreg
    cmd, icon = _command()
    C = winreg.HKEY_CURRENT_USER

    def setv(path, name, value):
        with winreg.CreateKeyEx(C, path, 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    base = rf"Software\Classes\{PROGID}"
    setv(base, "", "Frameline media")
    setv(base + r"\DefaultIcon", "", icon)
    setv(base + r"\shell\open\command", "", cmd)
    setv(base, "FriendlyTypeName", "Frameline media")
    setv(base + r"\Application", "ApplicationName", APP_NAME)
    setv(base + r"\Application", "ApplicationIcon", icon)
    setv(base + r"\Application", "ApplicationCompany", "Miguel Rato")
    app = r"Software\Classes\Applications\Frameline.exe"
    setv(app, "FriendlyAppName", APP_NAME)
    setv(app + r"\shell\open\command", "", cmd)
    caps = r"Software\Frameline\Capabilities"
    setv(caps, "ApplicationName", APP_NAME)
    setv(caps, "ApplicationDescription", "Frame-accurate media player and review tool")
    setv(caps, "ApplicationIcon", icon)
    for e in VIDEO_EXTS + IMAGE_EXTS + (SESSION_EXT,):
        setv(rf"Software\Classes\{e}\OpenWithProgids", PROGID, "")
        setv(app + r"\SupportedTypes", e, "")
        setv(caps + r"\FileAssociations", e, PROGID)
        # Explorer's per-user list is what the "Select a default app" picker reads
        with winreg.CreateKeyEx(C, EXPLORER_EXTS + rf"\{e}\OpenWithProgids", 0, winreg.KEY_WRITE) as k:
            winreg.SetValueEx(k, PROGID, 0, winreg.REG_NONE, b"")
        # the Settings picker only lists handlers Windows has already "announced" for the type
        with winreg.CreateKeyEx(C, TOASTS, 0, winreg.KEY_WRITE) as k:
            for name in (f"{PROGID}_{e}", rf"Applications\Frameline.exe_{e}"):
                winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, 0)
    setv(r"Software\RegisteredApplications", APP_NAME, caps)
    # .flsession files are ours alone: claim them outright
    setv(rf"Software\Classes\{SESSION_EXT}", "", PROGID)
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def make_default():
    """Register and open the OS page where the user confirms Frameline as default. Returns a message or None."""
    if sys.platform == "win32":
        register_windows()
        os.startfile(f"ms-settings:defaultapps?registeredAppUser={APP_NAME}")
        return None
    if sys.platform == "darwin":
        return ("To open all videos with Frameline: in Finder, select a video, press ⌘I, choose Frameline "
                "under “Open with”, then click “Change All…”. Repeat once per file type (.mp4, .mov, …).")
    try:
        subprocess.run(["xdg-mime", "default", "frameline.desktop", "video/mp4", "video/quicktime",
                        "video/x-matroska", "video/webm"], check=False)
    except Exception:
        pass
    return None


def unregister_windows():
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

    for e in VIDEO_EXTS + IMAGE_EXTS + (SESSION_EXT,):
        for path in (rf"Software\Classes\{e}\OpenWithProgids", EXPLORER_EXTS + rf"\{e}\OpenWithProgids"):
            try:
                with winreg.OpenKey(C, path, 0, winreg.KEY_WRITE) as k:
                    winreg.DeleteValue(k, PROGID)
            except OSError:
                pass
        for name in (f"{PROGID}_{e}", rf"Applications\Frameline.exe_{e}"):
            try:
                with winreg.OpenKey(C, TOASTS, 0, winreg.KEY_WRITE) as k:
                    winreg.DeleteValue(k, name)
            except OSError:
                pass
    try:
        with winreg.OpenKey(C, r"Software\RegisteredApplications", 0, winreg.KEY_WRITE) as k:
            winreg.DeleteValue(k, APP_NAME)
    except OSError:
        pass
    for path in (rf"Software\Classes\{PROGID}", r"Software\Classes\Applications\Frameline.exe", r"Software\Frameline",
                 rf"Software\Classes\{SESSION_EXT}"):
        delete_tree(path)
