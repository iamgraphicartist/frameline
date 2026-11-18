"""Local remote-control API (localhost only), so DCC tools/scripts can drive the player.

Send newline-delimited JSON to 127.0.0.1:18181, e.g.
    {"cmd": "open", "paths": ["C:/shots/sh010.mov"], "replace": true}
    {"cmd": "goto", "frame": 42}
    {"cmd": "play"} / {"cmd": "pause"} / {"cmd": "range", "in": 10, "out": 80}
    {"cmd": "marker", "frame": 12, "note": "fix arc"} / {"cmd": "compare", "path": "...", "mode": "wipe"}
    {"cmd": "status"}
"""
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QTcpServer, QHostAddress

PORT = 18181


class RemoteServer(QObject):
    command = Signal(dict, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._on_conn)
        self._bufs = {}

    def start(self):
        if self.server.isListening():
            return True
        return self.server.listen(QHostAddress.SpecialAddress.LocalHost, PORT)

    def stop(self):
        self.server.close()

    def _on_conn(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self._bufs[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._on_read(s))
            sock.disconnected.connect(lambda s=sock: self._bufs.pop(s, None))

    def _on_read(self, sock):
        self._bufs[sock] = self._bufs.get(sock, b"") + bytes(sock.readAll())
        while b"\n" in self._bufs[sock]:
            line, rest = self._bufs[sock].split(b"\n", 1)
            self._bufs[sock] = rest
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception as e:
                self.reply(sock, {"ok": False, "error": f"bad json: {e}"})
                continue
            self.command.emit(msg, sock)

    @staticmethod
    def reply(sock, obj):
        try:
            sock.write((json.dumps(obj) + "\n").encode("utf-8"))
        except Exception:
            pass
