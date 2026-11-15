#!/usr/bin/env python3
"""Install or remove Typing Assistant for the current user."""
import argparse
import os
from pathlib import Path
import shlex
from shutil import copyfile
import sys

DESKTOP_ID = "io.github.rajaxroy.TypingAssistant"
SOURCE = Path(__file__).resolve().parent
MARKER = "# Installed by Typing Assistant"


def desktop_argument(value):
    # The desktop entry string parser and Exec parser each process escapes.
    escaped = value.replace("%", "%%").replace("\\", "\\\\")
    for character in ('"', "`", "$"):
        escaped = escaped.replace(character, "\\" + character)
    return '"' + escaped.replace("\\", "\\\\") + '"'


def install(args):
    script = args.data_home / DESKTOP_ID / "typing_assistant.py"
    launcher = args.bin_dir / "typing-assistant"
    desktop = args.data_home / "applications" / f"{DESKTOP_ID}.desktop"

    if launcher.exists() or launcher.is_symlink():
        if launcher.is_symlink() or not launcher.is_file() or MARKER not in launcher.read_text(errors="replace"):
            raise SystemExit(f"Refusing to overwrite an existing launcher at {launcher}")

    if args.uninstall:
        for path in (desktop, launcher, script):
            path.unlink(missing_ok=True)
        if script.parent.exists() and not any(script.parent.iterdir()):
            script.parent.rmdir()
        print("Removed Typing Assistant")
        return

    try:
        from gi import require_version
        require_version("Atspi", "2.0")
        from gi.repository import Atspi
        from PySide6 import QtWidgets
    except (ImportError, ValueError) as error:
        raise SystemExit(f"Missing desktop dependencies: {error}. See README.md.") from error

    for path in (script, launcher, desktop):
        path.parent.mkdir(parents=True, exist_ok=True)
    copyfile(SOURCE / "typing_assistant.py", script)
    command = shlex.join([sys.executable, str(script)])
    launcher.write_text(f'#!/bin/sh\n{MARKER}\nexec {command} "$@"\n')
    launcher.chmod(0o755)
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Typing Assistant\n"
        "Comment=Check writing as you type\n"
        f"Exec={desktop_argument(str(launcher))}\n"
        "Icon=tools-check-spelling\n"
        "Terminal=false\n"
        "Categories=Utility;Accessibility;\n"
    )
    print(f"Installed launcher at {launcher}\nOpen Typing Assistant from your application menu.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    parser.add_argument("--data-home", type=Path, default=data_home)
    args = parser.parse_args()
    args.bin_dir = args.bin_dir.absolute()
    args.data_home = args.data_home.absolute()
    install(args)


if __name__ == "__main__":
    main()
