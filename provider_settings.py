"""Provider preferences and desktop keyring integration."""
import json
import os
from shutil import which

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)
from draft_model import DraftError, Provider

DEFAULT_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/free"
KEYRING_ATTRIBUTES = ["application", "io.github.rajaxroy.TypingAssistant", "credential", "api-key"]


class ProviderSettings(QObject):
    changed = Signal()
    operation_finished = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preferences = QSettings("TypingAssistant", "TypingAssistant")
        self.base = self.preferences.value("provider/base", DEFAULT_BASE, type=str)
        self.model = self.preferences.value("provider/model", DEFAULT_MODEL, type=str)
        self.remembered = self.preferences.value("provider/remembered", False, type=bool)
        self.provider = None
        self.process = None
        try:
            self.provider = Provider.from_environment()
        except DraftError:
            if self.remembered:
                QTimer.singleShot(0, self.load_saved_key)
        else:
            self.base = os.environ["TYPING_ASSISTANT_API_BASE"].strip()
            self.model = self.provider.model

    def set_provider(self, base, provider):
        self.base, self.model, self.provider = base.strip(), provider.model, provider
        self.preferences.setValue("provider/base", self.base)
        self.preferences.setValue("provider/model", self.model)
        self.changed.emit()

    def load_saved_key(self):
        if self.provider is not None or self.process is not None:
            return

        def loaded(success, data):
            if success and self.provider is None:
                try:
                    entry = json.loads(data)
                    provider = Provider.from_values(self.base, self.model, entry["key"])
                    if list(provider.scope) == entry["scope"]:
                        self.provider = provider
                except (DraftError, ValueError, KeyError, TypeError, AttributeError):
                    pass
            self.changed.emit()

        self.keyring("lookup", loaded)

    def remember(self, base, provider):
        def stored(success, _data):
            if success:
                self.remembered = True
                self.preferences.setValue("provider/remembered", True)
            self.set_provider(base, provider)
            self.operation_finished.emit("save", success)

        data = json.dumps({"scope": provider.scope, "key": provider.key}).encode("utf-8")
        self.keyring("store", stored, data)

    def forget(self):
        def cleared(success, _data):
            if success:
                self.remembered = False
                self.preferences.remove("provider/remembered")
                self.provider = None
                self.changed.emit()
            self.operation_finished.emit("forget", success)

        self.keyring("clear", cleared)

    def keyring(self, action, callback, data=None):
        executable = which("secret-tool")
        if executable is None or self.process is not None:
            callback(False, b"")
            return
        process = QProcess(self)
        self.process = process
        environment = QProcessEnvironment.systemEnvironment()
        environment.remove("TYPING_ASSISTANT_API_KEY")
        process.setProcessEnvironment(environment)
        timer = QTimer(process, singleShot=True, interval=30_000)

        def completed(success):
            if self.process is not process:
                return
            self.process = None
            timer.stop()
            output = bytes(process.readAllStandardOutput()) if success else b""
            process.deleteLater()
            callback(success, output)

        def started():
            if data is not None:
                process.write(data)
            process.closeWriteChannel()

        def failed(error):
            if error == QProcess.ProcessError.FailedToStart:
                completed(False)

        arguments = [action, *KEYRING_ATTRIBUTES]
        if action == "store":
            arguments.insert(1, "--label=Typing Assistant API key")
        process.started.connect(started)
        process.finished.connect(
            lambda code, status: completed(code == 0 and status == QProcess.ExitStatus.NormalExit)
        )
        process.errorOccurred.connect(failed)
        timer.timeout.connect(process.kill)
        timer.start()
        process.start(executable, arguments)
        self.changed.emit()


class ProviderSettingsDialog(QDialog):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("Model settings")
        self.setMinimumWidth(520)
        self.base = QLineEdit(settings.base)
        self.model = QLineEdit(settings.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Paste your provider API key")
        self.status = QLabel()
        self.status.setWordWrap(True)

        fields = QFormLayout()
        fields.addRow("API base URL", self.base)
        fields.addRow("Model ID", self.model)
        fields.addRow("API key", self.key)

        self.session = QPushButton("Use for this session")
        self.session.clicked.connect(lambda: self.save(False))
        self.remember = QPushButton("Save in keyring")
        self.remember.clicked.connect(lambda: self.save(True))
        self.forget = QPushButton("Forget saved key")
        self.forget.clicked.connect(self.forget_key)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        for button in (self.session, self.remember, self.forget, close):
            button.setAutoDefault(False)
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(fields)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        settings.changed.connect(self.refresh)
        settings.operation_finished.connect(self.handle_result)
        self.refresh()

    def refresh(self):
        busy = self.settings.process is not None
        self.session.setEnabled(not busy)
        self.remember.setEnabled(not busy)
        self.forget.setEnabled(self.settings.remembered and not busy)
        if self.settings.provider is not None:
            self.key.setPlaceholderText("Leave blank to keep the active key for this URL")

    def save(self, remember):
        base, model, key = self.base.text().strip(), self.model.text().strip(), self.key.text().strip()
        try:
            if not key and self.settings.provider is not None:
                active = self.settings.provider
                candidate = Provider.from_values(base, model, active.key)
                if candidate.scope == active.scope:
                    key = active.key
            provider = Provider.from_values(base, model, key)
        except DraftError as error:
            self.status.setText(str(error))
            return

        self.key.clear()
        if remember:
            self.status.setText("Waiting for the desktop keyring…")
            self.settings.remember(base, provider)
            self.refresh()
        else:
            self.settings.set_provider(base, provider)
            self.accept()

    def forget_key(self):
        self.status.setText("Removing the saved key…")
        self.settings.forget()
        self.refresh()

    def handle_result(self, action, success):
        self.refresh()
        if action == "save" and success:
            self.accept()
        elif action == "save":
            self.status.setText("The desktop keyring could not save the key. It is active for this session.")
        elif success:
            self.key.clear()
            self.key.setPlaceholderText("Paste your provider API key")
            self.status.setText("Saved key removed.")
        else:
            self.status.setText("Could not remove the saved key. Check that the desktop keyring is unlocked.")
