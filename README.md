# Typing Assistant for Linux

Typing Assistant checks English text while you write in desktop apps and browsers that expose editable fields through Linux accessibility. It shows a notification when it finds a correction. Review the suggested text before applying or copying it.

## Install

Use a graphical Linux session with Python 3.10+, a working session D-Bus, and AT-SPI. Install PyGObject, the AT-SPI 2.0 bindings, and PySide6 for the same Python interpreter.

**Arch Linux and EndeavourOS**

```sh
sudo pacman -S python-gobject at-spi2-core pyside6
```

**Fedora**

```sh
sudo dnf install python3-gobject at-spi2-core python3-pyside6
```

**Debian or Ubuntu with PySide6 in the distribution repository**

```sh
sudo apt install python3-gi at-spi2-core gir1.2-atspi-2.0 python3-pyside6.qtwidgets
```

**Debian or Ubuntu without a PySide6 package, including Ubuntu 24.04**

Install the system accessibility bindings, then use Qt's PySide6 wheel in a virtual environment that can see those bindings. Keep the virtual environment at this path while the utility is installed.

```sh
sudo apt install python3-gi at-spi2-core gir1.2-atspi-2.0 python3-venv libegl1 libxcb-cursor0
python3 -m venv --system-site-packages ~/.local/share/typing-assistant-venv
~/.local/share/typing-assistant-venv/bin/python -m pip install PySide6
~/.local/share/typing-assistant-venv/bin/python install.py
```

On other distributions, install equivalent packages or use the system accessibility bindings with a PySide6 wheel where one is available. [Qt for Python installation](https://doc.qt.io/qtforpython-6/gettingstarted.html) · [PyGObject installation](https://pygobject.gnome.org/getting_started.html)

From this repository, run the installer with the interpreter that has those dependencies. The installer above already covers the virtual-environment setup.

```sh
python3 install.py
```

Open **Typing Assistant** from your application menu, or run `~/.local/bin/typing-assistant`. You can also run `python3 typing_assistant.py` directly from the repository.

## Use

1. Type `i cant recieve teh file` into a regular text field and pause.
2. Open **Review latest text** from the tray or the Typing Assistant window. The preview should show `I can't receive the file`.
3. Choose **Format** to tidy spacing and extra blank lines, **Apply** in supported fields, or **Copy** to paste the revision yourself.
4. Use **Pause checking** or **Quit** from the tray or window.

The app uses a tray icon when available and otherwise opens a regular window. Use `--no-tray` to select the window explicitly. For startup at login, add Typing Assistant to your desktop's autostart settings. To remove the per-user launcher and installed script, run `python3 install.py --uninstall` from the repository.

## Grammar and privacy

The built-in checker handles a small set of English typos, contractions, and capitalization errors. For broader grammar and spelling checks, start a [local LanguageTool server](https://dev.languagetool.org/http-server.html) and run:

```sh
~/.local/bin/typing-assistant --languagetool-port 8081
```

Checks run on the focused field after a typing pause. Draft text stays in memory and the optional LanguageTool request goes to `127.0.0.1`. Notifications contain no draft text. The app skips fields reported as passwords or terminals and checks up to 4,000 characters per field.

## Compatibility

- Live detection was verified on KDE Plasma Wayland in a native Qt text field and a Firefox input. Firefox needed **Copy** in testing.
- The window fallback supports desktops without a tray. The utility is designed for graphical Wayland and X11 sessions with working AT-SPI, and behavior on other desktops and distributions still needs testing.
- Coverage depends on the app and field. Some rich, canvas-based, and sandboxed editors expose limited text or editing support. If direct replacement fails, the review window offers **Copy**.

If you test on another desktop, include your distro, desktop, Wayland or X11 session, and the app or editor you tried when reporting results. Use sample text you are comfortable sharing.

## License

[MIT](LICENSE).
