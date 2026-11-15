"""Signal the running assistant from a desktop shortcut."""
from hashlib import sha256
import os
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def socket_path():
    runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
    display = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY", "")
    session = sha256(display.encode()).hexdigest()[:12]
    return str(Path(runtime) / f"typing-assistant-{session}.sock")


class CaptureServer(QLocalServer):
    def __init__(self, capture, parent):
        super().__init__(parent)
        name = socket_path()
        self.lock = QLockFile(name + ".lock")
        self.lock.setStaleLockTime(0)
        if not self.lock.tryLock(0):
            raise RuntimeError("Typing Assistant is already running or its shortcut socket is locked.")
        self.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(name)
        if not self.listen(name):
            raise RuntimeError(f"Could not open the shortcut socket: {self.errorString()}")
        self.newConnection.connect(lambda: self.handle_capture(capture))

    def handle_capture(self, capture):
        while self.hasPendingConnections():
            client = self.nextPendingConnection()
            client.disconnected.connect(client.deleteLater)
            client.write(b"OK")
            client.disconnectFromServer()
        QTimer.singleShot(0, capture)


def request_capture():
    client = QLocalSocket()
    client.connectToServer(socket_path())
    return (
        client.waitForConnected(1000)
        and (client.bytesAvailable() or client.waitForReadyRead(3000))
        and bytes(client.read(2)) == b"OK"
    )
