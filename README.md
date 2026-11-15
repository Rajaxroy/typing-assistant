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

## Check or rewrite a full draft

Open **Model settings** from the tray, main window, or full-draft review. Enter the HTTPS base URL and model ID for a provider that supports [Chat Completions](https://developers.openai.com/api/reference/chat-completions/overview). For OpenRouter, use `https://openrouter.ai/api/v1` and `openrouter/free` or a specific model ID such as `google/gemma-4-26b-a4b-it:free`. Paste your [OpenRouter API key](https://openrouter.ai/settings/keys) into the masked field.

- **Use for this session** keeps the key in memory until you quit and saves the base URL and model as preferences.
- **Save in keyring** stores the key in the desktop Secret Service for future launches. This option needs `secret-tool` and a working desktop keyring. On Arch, `secret-tool` comes from `libsecret`; on Debian and Ubuntu it comes from `libsecret-tools`.
- **Forget saved key** removes the keyring entry. You can also remove it before uninstalling if you no longer plan to use the app.

Settings apply immediately. Existing terminal-based configuration still works and takes priority at launch if all three `TYPING_ASSISTANT_*` provider variables are set. Run `python3 install.py` again after an update to refresh a previously installed launcher and its files.

Create a custom global shortcut in your desktop settings. For example, in KDE Plasma, open **System Settings → Shortcuts → Add New → Command or Script**, use your launcher’s absolute path followed by `--capture`, and assign an available key combination such as **Ctrl+Alt+Shift+F**.

```text
/home/YOUR_USER/.local/bin/typing-assistant --capture
```

1. Finish writing the email or chat message. Leave the cursor in the draft body and press the shortcut while Typing Assistant is running.
2. Check that the left pane contains the full draft. If the editor exposes only part of it, or the editor is split into multiple fields, paste the complete text into that pane. You can also open **Full draft review** from the tray or the assistant window and paste the draft there.
3. Choose **Check grammar** for grammar, spelling, and punctuation, or **Make formal** to rewrite the draft in a professional tone. Each action starts from the left pane.
4. Review the complete result. Use **Apply** where direct replacement works, or **Copy revision** and paste it into your editor. A draft that was pasted or edited in the review window uses **Copy revision**.

The 4,000-character limit applies to automatic checks. Explicit actions accept up to 100,000 UTF-8 bytes and send the entire draft in one request. The selected model may have a lower context or output limit. If the provider rejects the request or returns an incomplete response, the app shows an error and leaves your draft intact.

## Grammar and privacy

Automatic checks run after a typing pause on the focused field. The built-in checker handles a small set of English typos, contractions, and capitalization errors. For broader automatic English checks, start a [local LanguageTool server](https://dev.languagetool.org/http-server.html) and run:

```sh
~/.local/bin/typing-assistant --languagetool-port 8081
```

Automatic checks use built-in rules or the optional loopback LanguageTool server. The external provider receives the draft only when you click **Check grammar** or **Make formal**. The review displays the provider before sending and the provider’s terms apply to those requests. Notifications contain no draft text. The app skips fields reported as passwords or terminals.

## Compatibility

- Live detection was verified on KDE Plasma Wayland in a native Qt field and a Firefox input. Full-draft capture was verified in a native Qt editor and a Firefox textarea using a 5,431-character draft and a mock provider. Firefox needed **Copy** in direct replacement testing.
- The window fallback supports desktops without a tray. The utility is designed for graphical Wayland and X11 sessions with working AT-SPI, and behavior on other desktops and distributions still needs testing.
- Coverage depends on the app and field. Some rich, canvas-based, and sandboxed editors expose limited text or editing support. If direct replacement fails, the review window offers **Copy**.

If you test on another desktop, include your distro, desktop, Wayland or X11 session, and the app or editor you tried when reporting results. Use sample text you are comfortable sharing.

## License

[MIT](LICENSE).
