#!/usr/bin/env python3
"""Check writing in accessible Linux desktop text fields."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection, HTTPException
import json
import os
import re
import sys
from time import monotonic
from urllib.parse import urlencode

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, Gio, GLib
from PySide6.QtCore import QCoreApplication, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton,
    QStyle, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from capture_shortcut import CaptureServer, request_capture
from draft_model import DraftError, MAX_DRAFT_BYTES, validate_draft
from draft_review import DraftReview
from provider_settings import ProviderSettings, ProviderSettingsDialog

MAX_LENGTH = 4000
ROLE = Atspi.Role
STATE = Atspi.StateType
BASIC_RULES = (
    (re.compile(r"\b(teh|adn|recieve|seperate|definately)\b"), {
        "teh": "the", "adn": "and", "recieve": "receive",
        "seperate": "separate", "definately": "definitely",
    }),
    (re.compile(r"\b(i|i'm|i've|i'll|i'd)\b"), {
        "i": "I", "i'm": "I'm", "i've": "I've", "i'll": "I'll", "i'd": "I'd",
    }),
    (re.compile(r"\b(cant|dont|doesnt|didnt|wont|isnt|arent)\b"), {
        "cant": "can't", "dont": "don't", "doesnt": "doesn't", "didnt": "didn't",
        "wont": "won't", "isnt": "isn't", "arent": "aren't",
    }),
)


def basic_check(value):
    for pattern, replacements in BASIC_RULES:
        value = pattern.sub(lambda match: replacements[match[0]], value)
    return value


def format_text(value):
    value = re.sub(r"(?m)^[\t ]+|[\t ]+$", "", value)
    value = re.sub(r"[\t ]{2,}", " ", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip("\n")


def apply_matches(value, matches):
    offsets = {0: 0}
    position = 0
    for index, character in enumerate(value, 1):
        position += 1 + (ord(character) > 0xFFFF)
        offsets[position] = index
    patches = []
    for match in matches:
        if not match["replacements"]:
            continue
        start = offsets.get(match["offset"])
        end = offsets.get(match["offset"] + match["length"])
        if start is not None and end is not None and start < end:
            patches.append((start, end, match["replacements"][0]["value"]))
    boundary = len(value)
    for start, end, replacement in sorted(patches, reverse=True):
        if end <= boundary:
            value = value[:start] + replacement + value[end:]
            boundary = start
    return value


def check_text(value, port):
    if port is None:
        return basic_check(value), False
    connection = HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(
            "POST", "/v2/check", urlencode({"text": value, "language": "en-US"}),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        if response.status != 200:
            return basic_check(value), True
        matches = json.loads(response.read(1_000_000))["matches"]
        return apply_matches(value, matches), False
    except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return basic_check(value), True
    finally:
        connection.close()


def read_field(source, require_focus=True, full=False):
    states = source.get_state_set()
    if not states.contains(STATE.EDITABLE) or states.contains(STATE.DEFUNCT):
        return None
    if require_focus and not states.contains(STATE.FOCUSED):
        return None
    if source.get_role() in (ROLE.PASSWORD_TEXT, ROLE.TERMINAL):
        return None
    if source.get_process_id() == os.getpid():
        return None
    attributes = source.get_attributes() or {}
    if attributes.get("text-input-type", "").lower() in {"password", "email", "url", "tel", "number", "search"}:
        return None
    if attributes.get("autocomplete", "").lower().startswith(("cc-", "one-time-code")):
        return None
    interface = source.get_text_iface()
    if interface is None:
        return None
    count = interface.get_character_count()
    if count <= 0 or (not full and count > MAX_LENGTH):
        return None
    if full and count > MAX_DRAFT_BYTES:
        raise DraftError("This field exceeds the full-draft size limit. Paste the text here after shortening it.")
    value = Atspi.Text.get_text(interface, 0, count)
    if full:
        if not value:
            return None
        byte_length = len(value.encode("utf-16-le")) // 2
        if count not in (len(value), byte_length) or interface.get_character_count() != count:
            raise DraftError("The field did not expose a stable, complete draft. Paste the full text here.")
        validate_draft(value)
    return value


def replaceable(source):
    states = source.get_state_set()
    return (
        source.get_role() in (ROLE.ENTRY, ROLE.TEXT)
        and states.contains(STATE.SINGLE_LINE)
        and source.get_editable_text_iface() is not None
    )


class Assistant(QWidget):
    def __init__(self, port, use_tray=None):
        if use_tray is None:
            use_tray = QSystemTrayIcon.isSystemTrayAvailable()
        super().__init__(None, Qt.WindowType.Tool if use_tray else Qt.WindowType.Window)
        self.use_tray = use_tray
        self.notification_bus = None
        if not use_tray:
            try:
                self.notification_bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            except GLib.Error:
                pass
        self.setWindowTitle("Typing Assistant")
        self.resize(390, 100)
        self.port = port
        self.enabled = True
        self.focused_field = None
        self.full_review = None
        self.reply_review = None
        self.settings_dialog = None
        self.provider_settings = ProviderSettings(self)
        self.draft_executor = ThreadPoolExecutor(max_workers=1)
        self.source = None
        self.original = ""
        self.corrected = ""
        self.pending = None
        self.last_notification = float("-inf")
        self.executor = ThreadPoolExecutor(max_workers=1)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.preview = QPlainTextEdit(readOnly=True)
        self.preview.setMaximumHeight(125)
        self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row = QHBoxLayout()
        self.format_button = QPushButton("Format")
        self.format_button.clicked.connect(self.format_suggestion)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy)
        close = QPushButton("Dismiss")
        close.clicked.connect(self.reset)
        for button in (self.format_button, self.apply_button, self.copy_button, close):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.preview)
        layout.addLayout(row)

        fallback_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        icon = QIcon.fromTheme("tools-check-spelling", fallback_icon)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("Typing Assistant")
        self.menu = QMenu()
        self.review = self.menu.addAction("Review latest text", self.open_review)
        self.review.setEnabled(False)
        self.menu.addAction("Open full draft review", self.capture_full_draft)
        self.menu.addAction("Reply to copied text", self.open_reply)
        self.menu.addAction("Model settings", self.open_model_settings)
        self.tray.messageClicked.connect(self.open_review)
        self.tray.activated.connect(self.tray_activated)
        self.pause = self.menu.addAction("Pause checking", self.toggle)
        self.menu.addAction("Quit", QApplication.instance().quit)
        self.tray.setContextMenu(self.menu)
        if use_tray:
            self.tray.show()
        else:
            controls = QHBoxLayout()
            self.review_button = QPushButton("Review latest text")
            self.review.changed.connect(self.sync_review_button)
            self.review_button.clicked.connect(self.open_review)
            controls.addWidget(self.review_button)
            full_review_button = QPushButton("Full draft review")
            full_review_button.clicked.connect(self.capture_full_draft)
            controls.addWidget(full_review_button)
            reply_button = QPushButton("Reply to copied text")
            reply_button.clicked.connect(self.open_reply)
            controls.addWidget(reply_button)
            settings_button = QPushButton("Model settings")
            settings_button.clicked.connect(self.open_model_settings)
            controls.addWidget(settings_button)
            self.pause_button = QPushButton()
            self.pause.changed.connect(self.sync_pause_button)
            self.pause_button.clicked.connect(self.toggle)
            controls.addWidget(self.pause_button)
            quit_button = QPushButton("Quit")
            quit_button.clicked.connect(QApplication.instance().quit)
            controls.addWidget(quit_button)
            layout.addLayout(controls)
            self.sync_review_button()
            self.sync_pause_button()

        self.debounce = QTimer(self, singleShot=True, interval=650)
        self.debounce.timeout.connect(self.inspect)
        self.poll = QTimer(self, interval=35)
        self.poll.timeout.connect(self.pump)
        self.listener = Atspi.EventListener.new(self.on_accessibility_event)
        for event in ("object:text-changed", "object:state-changed:focused"):
            if not self.listener.register(event):
                raise RuntimeError(f"Could not subscribe to {event}")
        self.poll.start()
        self.reset()
        if not use_tray:
            self.show()

    def sync_review_button(self):
        self.review_button.setEnabled(self.review.isEnabled())

    def sync_pause_button(self):
        self.pause_button.setText(self.pause.text())

    def toggle(self):
        self.enabled = not self.enabled
        self.pause.setText("Pause checking" if self.enabled else "Resume checking")
        self.reset()

    def reset(self):
        self.source = None
        self.original = ""
        self.corrected = ""
        self.preview.clear()
        self.review.setEnabled(False)
        if self.use_tray:
            self.hide()
        else:
            self.preview.hide()
            self.format_button.hide()
            self.apply_button.hide()
            self.copy_button.hide()
            self.status.setText("Waiting for text…" if self.enabled else "Checking paused")
        self.debounce.stop()
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None

    def on_accessibility_event(self, event, *_):
        try:
            source = event.source
            if source is None or source.get_process_id() == os.getpid():
                return
            states = source.get_state_set()
            if not (states.contains(STATE.FOCUSED) and states.contains(STATE.EDITABLE)):
                return
        except (GLib.Error, RuntimeError):
            return
        self.focused_field = source
        if self.enabled and event.type.startswith("object:text-changed"):
            self.reset()
            self.source = source
            self.debounce.start()

    def capture_full_draft(self):
        self.pump()
        source = self.focused_field
        original = ""
        note = "No readable focused draft was captured. Paste the full draft into the box."
        replace = None
        try:
            if source is not None:
                original = read_field(source, full=True) or ""
                if original:
                    note = "Check that the full draft is shown. If the app exposed only part of it, paste the complete text here."
                    if replaceable(source):
                        def replace(revised, done):
                            self.replace_full_draft(source, original, revised, done)
        except DraftError as error:
            note = str(error)
        except (GLib.Error, RuntimeError):
            pass
        if self.full_review is not None:
            if not original:
                self.full_review.raise_()
                self.full_review.activateWindow()
                return
            self.full_review.close()
        review = DraftReview(
            self.draft_executor, self.provider_settings, self.open_model_settings, original, note, replace
        )
        review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        review.finished.connect(self.clear_full_review)
        self.full_review = review
        review.show()
        review.raise_()
        review.activateWindow()

    def open_reply(self):
        if self.reply_review is None:
            review = DraftReview(
                self.draft_executor, self.provider_settings, self.open_model_settings,
                QApplication.clipboard().text(),
                "Review the copied message and add any facts, tone, or instructions for your reply.",
                reply=True,
            )
            review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            review.finished.connect(self.clear_reply_review)
            self.reply_review = review
        self.reply_review.show()
        self.reply_review.raise_()
        self.reply_review.activateWindow()

    def clear_reply_review(self, _result):
        self.reply_review = None

    def open_model_settings(self):
        if self.settings_dialog is None:
            dialog = ProviderSettingsDialog(self.provider_settings)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.finished.connect(self.clear_settings_dialog)
            self.settings_dialog = dialog
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def clear_settings_dialog(self, _result):
        self.settings_dialog = None

    def clear_full_review(self, _result):
        self.full_review = None

    def replace_full_draft(self, source, original, revised, done):
        try:
            if not replaceable(source) or read_field(source, require_focus=False, full=True) != original:
                done(False)
                return
            editor = source.get_editable_text_iface()
            if not Atspi.EditableText.set_text_contents(editor, revised):
                done(False)
                return
        except (DraftError, GLib.Error, RuntimeError):
            done(False)
            return

        review = self.full_review

        def confirm():
            if self.full_review is not review:
                return
            try:
                done(read_field(source, require_focus=False, full=True) == revised)
            except (DraftError, GLib.Error, RuntimeError):
                done(False)

        QTimer.singleShot(500, confirm)

    def current(self, require_focus=True):
        try:
            return read_field(self.source, require_focus) if self.source is not None else None
        except (GLib.Error, RuntimeError):
            return None

    def inspect(self):
        value = self.current()
        if not value or not re.search(r"[A-Za-z]{2}", value) or len(value.strip()) < 5:
            return
        self.original = value
        self.pending = self.executor.submit(check_text, value, self.port)

    def pump(self):
        self.poll.stop()
        try:
            context = GLib.MainContext.default()
            for _ in range(24):
                if not context.pending():
                    break
                context.iteration(False)
            if self.pending is None:
                return
            future = self.pending
            if not future.done():
                return
            self.pending = None
            if self.current() != self.original:
                return
            self.corrected, fallback = future.result()
            if fallback:
                self.tray.setToolTip("Typing Assistant · LanguageTool unavailable, using basic checks")
            else:
                self.tray.setToolTip("Typing Assistant")
            self.review.setEnabled(True)
            if not self.use_tray:
                status = "Writing suggestions available" if self.corrected != self.original else "Text ready to review"
                self.status.setText(status if not fallback else f"{status} · Using basic checks")
            if self.corrected != self.original and monotonic() - self.last_notification >= 8:
                self.last_notification = monotonic()
                self.notify()
        finally:
            self.poll.start()

    def notify(self):
        title, body = "Typing Assistant", "Writing suggestions available"
        if self.use_tray:
            self.tray.showMessage(title, body)
        elif self.notification_bus is not None:
            self.notification_bus.call(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications", "Notify",
                GLib.Variant("(susssasa{sv}i)", (title, 0, "", title, body, [], {}, -1)),
                None, Gio.DBusCallFlags.NONE, 2000, None, None,
            )

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_review()

    def open_review(self):
        if self.review.isEnabled():
            self.show_suggestion()
            self.raise_()
            self.activateWindow()

    def show_suggestion(self):
        has_change = self.corrected != self.original
        self.status.setText("Review suggested text" if has_change else "No corrections found")
        self.preview.setVisible(has_change)
        self.preview.setPlainText(self.corrected if has_change else "")
        try:
            can_apply = has_change and self.source is not None and replaceable(self.source)
        except (GLib.Error, RuntimeError):
            can_apply = False
        self.apply_button.setVisible(can_apply)
        self.apply_button.setEnabled(can_apply)
        self.copy_button.setVisible(has_change)
        self.format_button.show()
        self.format_button.setEnabled(format_text(self.corrected) != self.corrected)
        self.adjustSize()
        self.show()

    def format_suggestion(self):
        if self.current(require_focus=False) != self.original:
            self.reset()
            return
        self.corrected = format_text(self.corrected)
        self.show_suggestion()

    def copy(self):
        QApplication.clipboard().setText(self.corrected)
        self.reset()

    def apply(self):
        if self.current(require_focus=False) != self.original:
            self.reset()
            return
        try:
            if replaceable(self.source):
                editor = self.source.get_editable_text_iface()
                revised = self.corrected
                source = self.source
                if Atspi.EditableText.set_text_contents(editor, revised):
                    self.apply_button.setEnabled(False)
                    QTimer.singleShot(500, lambda: self.confirm_apply(source, revised))
                    return
        except (GLib.Error, RuntimeError):
            pass
        self.show_apply_failure()

    def confirm_apply(self, source, revised):
        if self.source is not source or self.corrected != revised:
            return
        if self.current(require_focus=False) == revised:
            self.reset()
        else:
            self.show_apply_failure()

    def show_apply_failure(self):
        self.apply_button.hide()
        self.status.setText("Could not verify the change. Use Copy.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languagetool-port", type=int, choices=range(1, 65536),
                        metavar="PORT", help="use a local LanguageTool server")
    parser.add_argument("--no-tray", action="store_true", help="show a regular desktop window")
    parser.add_argument("--capture", action="store_true", help="review the full draft in the focused editor")
    args = parser.parse_args()
    if args.capture:
        command = QCoreApplication([sys.argv[0]])
        if not request_capture():
            parser.exit(1, "Could not reach Typing Assistant. Start it in this desktop session first.\n")
        return 0
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        parser.exit(1, "Start Typing Assistant from a graphical Linux desktop session.\n")
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Typing Assistant")
    app.setDesktopFileName("io.github.rajaxroy.TypingAssistant")
    use_tray = not args.no_tray and QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not use_tray)
    if Atspi.init() != 0:
        parser.exit(1, "Could not connect to the desktop accessibility bus.\n")
    Atspi.set_timeout(500, 2000)
    try:
        assistant = Assistant(args.languagetool_port, use_tray)
        shortcut = CaptureServer(assistant.capture_full_draft, assistant)
    except (GLib.Error, RuntimeError) as error:
        parser.exit(1, f"Could not start Typing Assistant: {error}\n")
    try:
        return app.exec()
    finally:
        shortcut.close()
        shortcut.lock.unlock()
        assistant.executor.shutdown(wait=False, cancel_futures=True)
        assistant.draft_executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    sys.exit(main())
