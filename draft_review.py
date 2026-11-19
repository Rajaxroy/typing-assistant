"""Review a captured draft and request an explicit external edit."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)
from draft_model import DraftError, generate_reply, rewrite, validate_draft


class DraftReview(QDialog):
    def __init__(self, executor, provider_settings, open_settings, original="", capture_note="", replace=None, reply=False):
        super().__init__()
        self.reply_mode = reply
        self.executor = executor
        self.provider_settings = provider_settings
        self.captured = original
        self.replace = replace
        self.pending = None
        self.applying = False
        self.setWindowTitle("Draft a reply" if reply else "Review full draft")
        self.resize(920, 510)

        self.note = QLabel(capture_note)
        self.note.setWordWrap(True)
        self.provider_note = QLabel()
        self.provider_note.setTextFormat(Qt.TextFormat.PlainText)
        self.provider_note.setWordWrap(True)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.original = QPlainTextEdit(original)
        self.original.setPlaceholderText("Paste the received email or chat message" if reply else "Paste your full draft here")
        self.original.textChanged.connect(self.clear_result)
        self.revised = QPlainTextEdit(readOnly=True)
        self.revised.setPlaceholderText("The revised draft will appear here")

        self.context = QPlainTextEdit()
        self.context.setPlaceholderText(
            "For example: Thank them, say I’m available Friday after 2 pm, and ask for a meeting link. Keep it friendly."
        )
        self.context.setMaximumHeight(110)
        self.context.textChanged.connect(self.clear_result)
        self.grammar = QPushButton("Generate reply" if reply else "Check grammar")
        self.grammar.clicked.connect(lambda: self.request("reply" if self.reply_mode else "grammar"))
        self.formal = QPushButton("Make formal")
        self.formal.clicked.connect(lambda: self.request("formal"))
        self.apply = QPushButton("Apply")
        self.apply.clicked.connect(self.apply_result)
        self.copy = QPushButton("Copy reply" if reply else "Copy revision")
        self.copy.clicked.connect(self.copy_result)
        settings_button = QPushButton("Model settings")
        settings_button.clicked.connect(open_settings)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        for button in (self.grammar, self.formal, self.apply, self.copy, settings_button, close):
            button.setAutoDefault(False)
            actions.addWidget(button)

        editors = QHBoxLayout()
        for label, editor in ((("Received message" if reply else "Full draft"), self.original), (("Reply" if reply else "Revised draft"), self.revised)):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(editor)
            editors.addLayout(column)

        layout = QVBoxLayout(self)
        layout.addWidget(self.note)
        layout.addLayout(editors)
        if reply:
            self.formal.hide()
            self.apply.hide()
            layout.addWidget(QLabel("How would you like to reply?"))
            layout.addWidget(self.context)
        layout.addWidget(self.provider_note)
        layout.addWidget(self.status)
        layout.addLayout(actions)
        self.timer = QTimer(self, interval=70)
        self.timer.timeout.connect(self.finish_request)
        provider_settings.changed.connect(self.configure_provider)
        self.configure_provider()
        self.clear_result()

    def configure_provider(self):
        self.provider = self.provider_settings.provider
        if self.provider is None:
            self.provider_note.setText("Open Model settings to set your provider, model, and API key.")
        else:
            self.provider_note.setText(
                f"Clicking a writing action sends the text and any reply context to {self.provider.destination} "
                f"using {self.provider.model}."
            )
        self.enable_writing_actions(self.provider is not None and self.pending is None and not self.applying)

    def enable_writing_actions(self, enabled):
        self.grammar.setEnabled(enabled)
        self.formal.setEnabled(enabled)

    def clear_result(self):
        self.revised.clear()
        self.apply.setEnabled(False)
        self.copy.setEnabled(False)
        if self.pending is None and not self.applying:
            self.status.clear()

    def request(self, mode):
        if self.provider is None or self.pending is not None or self.applying:
            return
        text = self.original.toPlainText()
        # Qt normalizes some line endings. Send the exact captured draft when the
        # review text has not been edited.
        if not self.original.document().isModified():
            text = self.captured
        try:
            validate_draft(text)
        except DraftError as error:
            self.status.setText(str(error))
            return
        self.clear_result()
        if self.reply_mode:
            self.pending = self.executor.submit(generate_reply, self.provider, text, self.context.toPlainText())
        else:
            self.pending = self.executor.submit(rewrite, self.provider, text, mode)
        self.context.setReadOnly(True)
        self.enable_writing_actions(False)
        self.original.setReadOnly(True)
        self.status.setText(f"Waiting for {self.provider.destination}…")
        self.timer.start()

    def finish_request(self):
        future = self.pending
        if future is None or not future.done():
            return
        self.pending = None
        self.timer.stop()
        self.original.setReadOnly(False)
        self.context.setReadOnly(False)
        self.enable_writing_actions(self.provider is not None)
        try:
            self.result = future.result()
        except DraftError as error:
            self.status.setText(str(error))
            return
        self.revised.setPlainText(self.result)
        changed = self.reply_mode or self.result != (
            self.original.toPlainText() if self.original.document().isModified() else self.captured
        )
        self.copy.setEnabled(changed)
        can_apply = (
            changed and self.replace is not None and not self.original.document().isModified()
            and len(self.result.splitlines()) == 1 and not self.result.endswith(("\n", "\r"))
        )
        self.apply.setEnabled(can_apply)
        if self.reply_mode:
            self.status.setText("Review your reply, then copy it into your email or chat.")
        else:
            self.status.setText("Review the full revision before applying or copying it." if changed else "No changes suggested.")

    def apply_result(self):
        self.apply.setEnabled(False)
        self.enable_writing_actions(False)
        self.applying = True
        self.original.setReadOnly(True)
        self.status.setText("Checking whether the original field accepted the revision…")
        self.replace(self.result, self.finish_apply)

    def finish_apply(self, applied):
        self.applying = False
        if applied:
            self.accept()
        else:
            self.original.setReadOnly(False)
            self.enable_writing_actions(self.provider is not None)
            self.status.setText("Could not verify the replacement. Use Copy revision.")

    def copy_result(self):
        QApplication.clipboard().setText(self.result)
        self.accept()

    def done(self, result):
        self.timer.stop()
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
        self.original.clear()
        self.context.clear()
        self.revised.clear()
        self.captured = ""
        self.result = ""
        super().done(result)
