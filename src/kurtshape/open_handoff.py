"""Open a project handed over by a second launch in the KurtShape that is already running.

``launch-kurtshape.ps1 -FilePath`` (double-clicking an .FCStd) first runs
``tools/open-in-running-app.ps1``. The running app listens on a local pipe named after
its session folder and limited to the current Windows user; when it answers, it comes
to the front and opens the file like Open does, and the launch ends instead of
starting a second KurtShape.

One UTF-8 JSON line each way: on connect the app sends ``{"app": "KurtShape", "pid": N}``;
the launcher sends ``{"open": "<absolute .FCStd path>"}``; the app answers
``{"ok": true}`` (then opens the file) or ``{"ok": false, "message": ...}``.
"""
import hashlib
import json
import os
from pathlib import Path

import FreeCAD as App
from PySide6 import QtCore, QtNetwork, QtWidgets

MAX_REQUEST_BYTES = 64 * 1024


def pipe_name(session_dir):
    """The pipe for a session folder; tools/open-in-running-app.ps1 derives the same name."""
    key = os.path.normcase(os.path.abspath(str(session_dir)))
    return "KurtShape-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def same_file(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


class OpenHandoff(QtCore.QObject):
    def __init__(self, panel, session_dir):
        super().__init__(panel)
        self.panel = panel
        self.pending = []
        self.name = pipe_name(session_dir)
        self.server = QtNetwork.QLocalServer(self)
        self.server.setSocketOptions(QtNetwork.QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        # Fails when another KurtShape on this session already listens; that one takes the files.
        self.listening = self.server.listen(self.name)
        # Requests that arrive while a dialog is open wait until it closes.
        self.retry = QtCore.QTimer(self)
        self.retry.setInterval(250)
        self.retry.timeout.connect(self._open_pending)

    def close(self):
        self.retry.stop()
        self.pending.clear()
        self.server.close()

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            state = {"data": bytearray(), "done": False}
            socket.readyRead.connect(lambda socket=socket, state=state: self._read(socket, state))
            socket.disconnected.connect(socket.deleteLater)
            socket.write(json.dumps({"app": "KurtShape", "pid": os.getpid()}).encode("utf-8") + b"\n")
            socket.flush()

    def _read(self, socket, state):
        if state["done"]:
            socket.readAll()
            return
        state["data"].extend(bytes(socket.readAll()))
        if b"\n" not in state["data"]:
            if len(state["data"]) > MAX_REQUEST_BYTES:
                state["done"] = True
                socket.abort()
            return
        state["done"] = True
        line = bytes(state["data"]).split(b"\n", 1)[0]
        try:
            reply = self.request(json.loads(line.decode("utf-8")))
        except ValueError:  # invalid JSON or UTF-8
            reply = {"ok": False, "message": "KurtShape could not read the open request."}
        socket.write(json.dumps(reply).encode("utf-8") + b"\n")
        socket.flush()
        socket.disconnectFromServer()

    def request(self, message):
        path = message.get("open") if isinstance(message, dict) else None
        if not isinstance(path, str) or not path:
            return {"ok": False, "message": "KurtShape expected a project path to open."}
        path = Path(path)
        if not path.is_absolute() or path.suffix.lower() != ".fcstd" or not path.is_file():
            return {"ok": False, "message": "KurtShape opens existing native .FCStd projects only: " + str(path)}
        self.pending.append(str(path))
        self.bring_to_front()
        QtCore.QTimer.singleShot(0, self._open_pending)
        return {"ok": True}

    def bring_to_front(self):
        window = self.panel.main
        if not window.isVisible():  # hidden agent and test apps stay hidden
            return
        state = window.windowState()
        if state & QtCore.Qt.WindowState.WindowMinimized:
            # Qt's restore recipe: keeps a maximized window maximized.
            window.setWindowState((state & ~QtCore.Qt.WindowState.WindowMinimized) | QtCore.Qt.WindowState.WindowActive)
        window.raise_()
        window.activateWindow()

    def _open_pending(self):
        if QtWidgets.QApplication.activeModalWidget() is not None:
            self.retry.start()
            return
        self.retry.stop()
        while self.pending:
            self.open(self.pending.pop(0))

    def open(self, path):
        """Open like Open does; a project that is already open becomes the active tab instead."""
        for doc in App.listDocuments().values():
            if doc.FileName and same_file(doc.FileName, path):
                if App.activeDocument() is not doc:
                    self.panel.general_actions._activate(doc.Name)
                return doc
        return self.panel.open_path(path)
