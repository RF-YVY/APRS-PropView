"""Environment isolation for Windows setup and post-update launches."""
import os
import hashlib
import hmac
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

MAX_INSTALLER_BYTES = 256 * 1024 * 1024
MIN_INSTALLER_BYTES = 1024 * 1024
DOWNLOAD_HOSTS = {'github.com', 'objects.githubusercontent.com',
                  'github-releases.githubusercontent.com', 'release-assets.githubusercontent.com'}


def validate_download_url(url, initial=False):
    from server.update_checker import GITHUB_REPO
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc.lower() not in DOWNLOAD_HOSTS or parsed.fragment or
            (initial and (parsed.netloc.lower() != 'github.com' or
                          not parsed.path.lower().startswith('/' + GITHUB_REPO.lower() + '/releases/download/')))):
        raise ValueError('Installer URL is not a trusted project release URL.')


class TrustedReleaseRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def release_opener():
    from server.update_checker import _github_ssl_context
    return urllib.request.build_opener(TrustedReleaseRedirects(),
                                       urllib.request.HTTPSHandler(context=_github_ssl_context()))


def create_staging_directory():
    directory = Path(tempfile.mkdtemp(prefix='APRSPropViewUpdate-'))
    try:
        if os.name == 'nt':
            # Python 3.11 chmod does not establish an owner-only Windows DACL.
            system32 = Path(os.environ['SystemRoot']) / 'System32'
            identity = subprocess.check_output([str(system32 / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                                               text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            match = re.search(r'S-1-5-(?:\d+-)*\d+', identity)
            if not match:
                raise RuntimeError('Cannot identify installer staging owner')
            subprocess.run([str(system32 / 'icacls.exe'), str(directory), '/inheritance:r', '/grant:r',
                            f'*{match.group()}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F',
                            '*S-1-5-32-544:(OI)(CI)F'], check=True, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            directory.chmod(0o700)
        return directory
    except Exception:
        shutil.rmtree(directory)
        raise


def verify_installer(path, expected_sha256):
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256 or ''):
        raise ValueError('Release has no valid SHA-256 digest')
    digest = hashlib.sha256()
    size = 0
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b''):
            size += len(chunk)
            if size > MAX_INSTALLER_BYTES:
                raise ValueError('Installer exceeds size limit')
            digest.update(chunk)
    if size < MIN_INSTALLER_BYTES or not hmac.compare_digest(digest.hexdigest(), expected_sha256.lower()):
        raise ValueError('Installer size or SHA-256 verification failed')


def download_installer(url, filename, expected_sha256, expected_size, progress):
    validate_download_url(url, initial=True)
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected_sha256 or ''):
        raise ValueError('Release is missing its SHA-256 digest')
    if type(expected_size) is not int or not MIN_INSTALLER_BYTES <= expected_size <= MAX_INSTALLER_BYTES:
        raise ValueError('Release installer size is missing or exceeds the limit')
    filename = Path(filename).name
    if not re.fullmatch(r'APRSPropViewSetup[A-Za-z0-9._-]*\.exe', filename, re.IGNORECASE):
        raise ValueError('Unexpected installer filename')
    directory = create_staging_directory()
    target = directory / filename
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'APRSPropView secure updater'})
        with release_opener().open(request, timeout=120) as response:
            validate_download_url(response.geturl())
            length = response.headers.get('Content-Length')
            if length is not None and int(length) != expected_size:
                raise ValueError('Installer length differs from release metadata')
            progress.update(total_bytes=expected_size, downloaded_bytes=0)
            with target.open('xb') as stream:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    progress['downloaded_bytes'] += len(chunk)
                    if progress['downloaded_bytes'] > expected_size:
                        raise ValueError('Installer exceeded declared release size')
                    stream.write(chunk)
        if progress['downloaded_bytes'] != expected_size:
            raise ValueError('Installer download was truncated')
        verify_installer(target, expected_sha256)
        return str(target)
    except Exception:
        shutil.rmtree(directory)
        raise


def installer_environment():
    # A one-file app's temporary extraction directory disappears on shutdown.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('_PYI_', '_MEIPASS'))}
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env
