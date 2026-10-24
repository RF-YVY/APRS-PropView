"""Password setup/recovery UI that runs on the host, never through a public API."""
import logging
import os
import subprocess
import sys

from server.operator_auth import OperatorAuth, set_password
from server.update_install import installer_environment

logger = logging.getLogger('propview.desktop')


def set_console_password(path):
    """Set host credentials without a display or exposing a password in argv."""
    from getpass import getpass
    password = getpass('New operator password: ')
    if password != getpass('Confirm password: '):
        raise ValueError('Passwords do not match.')
    set_password(path, password)
    print('Operator password saved.')


def show_password_dialog(path):
    """Return True after saving; cancellation/unavailable desktop leaves settings unchanged."""
    if sys.platform not in {'win32', 'darwin'} and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        logger.info('No desktop available for operator password setup; dashboard remains read-only.')
        return False
    try:
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
    except Exception:
        logger.warning('Password window unavailable. Use the host desktop to set/reset the operator password.')
        return False
    saved = False
    auth = OperatorAuth(path)
    auth.reload()
    root.title('APRS PropView — Operator password')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.grid()
    ttk.Label(frame, text='Set your operator password', font=('Segoe UI', 15, 'bold')).grid(sticky='w')
    ttk.Label(frame, text='This password protects settings and transmit controls for remote browsers.\n'
                         'Forgot your password? Set a replacement here on this computer.', justify='left').grid(sticky='w', pady=(8, 16))
    password, confirmation = tk.StringVar(), tk.StringVar()
    for row, (label, value) in enumerate((('New password (6–256 characters)', password), ('Confirm password', confirmation)), 2):
        ttk.Label(frame, text=label).grid(row=row * 2, sticky='w')
        entry = ttk.Entry(frame, textvariable=value, show='•', width=48)
        entry.grid(row=row * 2 + 1, sticky='ew', pady=(4, 12))
        if row == 2:
            entry.focus_set()
    automatic = tk.BooleanVar(value=bool((auth.record or {}).get('local_auto_login', True)))
    ttk.Checkbutton(frame, text='Automatically sign in browsers opened by this computer', variable=automatic).grid(row=8, sticky='w', pady=(4, 8))
    ttk.Label(frame, text='Public viewers stay read-only. Local automatic sessions last 8 hours.').grid(row=9, sticky='w')
    message = tk.StringVar()
    ttk.Label(frame, textvariable=message, foreground='#b42318', wraplength=460).grid(row=10, sticky='w', pady=10)

    def save():
        nonlocal saved
        if password.get() != confirmation.get():
            message.set('Passwords do not match. Please try again.')
            return
        try:
            set_password(path, password.get(), automatic.get())
        except (ValueError, OSError) as exc:
            message.set(str(exc))
            return
        saved = True
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=11, sticky='e')
    ttk.Button(buttons, text='Not now', command=root.destroy).pack(side='left', padx=8)
    ttk.Button(buttons, text='Save password', command=save).pack(side='left')
    root.bind('<Return>', lambda event: save())
    root.mainloop()
    return saved


def launch_password_dialog():
    """Use a separate GUI process so Tk owns its main thread on every desktop OS."""
    command = [sys.executable]
    if not getattr(sys, 'frozen', False):
        from pathlib import Path
        command.append(str(Path(__file__).resolve().parent.parent / 'main.py'))
    command.append('--operator-password-dialog')
    return subprocess.Popen(command, env=installer_environment(), close_fds=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
