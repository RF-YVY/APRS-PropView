"""Archive a host-native Linux/macOS build for GitHub release distribution."""
import platform
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
version = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT / 'main.py').read_text(encoding='utf-8'), re.M).group(1)
machine = platform.machine().lower()
arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine, machine)
system = 'macos' if sys.platform == 'darwin' else 'linux'
binary = ROOT / 'dist' / ('APRS PropView.app' if system == 'macos' else 'APRSPropView')
if not binary.exists():
    raise SystemExit(f'Build artifact missing: {binary}')
stem = f'APRSPropView-{version}-{system}-{arch}'
archive = ROOT / 'dist' / f'{stem}.tar.gz'
with tarfile.open(archive, 'w:gz') as output:
    output.add(binary, arcname=f'{stem}/{binary.name}')
    for name in ['CHANGELOG.md', 'LICENSE', 'NOTICE', 'TRADEMARKS.md', 'docs/CROSS_PLATFORM_SETUP.md', 'docs/MODEM_THIRD_PARTY_NOTICES.txt']:
        output.add(ROOT / name, arcname=f'{stem}/{Path(name).name}')
print(archive)
