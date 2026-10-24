"""Environment isolation for Windows setup and post-update launches."""
import os


def installer_environment():
    # A one-file app's temporary extraction directory disappears on shutdown.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('_PYI_', '_MEIPASS'))}
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env
