"""Reject malformed UTF-8 and common mojibake in shipped text sources."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUSPECT = re.compile(
    r'(?:\u00e2[\u0080-\u00ff\u0152\u0153\u0178\u0192\u02c6\u02dc\u2013-\u203a\u20ac\u2122]'
    r'|\u00c3[\u0080-\u00bf]|\u00c2[\u0080-\u00bf]|\u00f0\u0178|\ufffd|[\x80-\x9f])'
)
EXTENSIONS = {'.py', '.js', '.cjs', '.css', '.html', '.md', '.json', '.toml', '.txt', '.cpp'}


def check(root=ROOT):
    files = [*root.glob('*.md'), *root.glob('*.py'), root / 'config.toml.example']
    for folder in ('server', 'static', 'docs', 'scripts', 'native'):
        files.extend(p for p in (root / folder).rglob('*')
                     if p.suffix in EXTENSIONS and not {'bin', '__pycache__'} & set(p.parts))
    failures = []
    for path in files:
        try:
            content = path.read_text(encoding='utf-8-sig')
        except UnicodeError:
            failures.append(f'{path.relative_to(root)}: invalid UTF-8')
            continue
        for number, line in enumerate(content.splitlines(), 1):
            if SUSPECT.search(line):
                failures.append(f'{path.relative_to(root)}:{number}: corrupted text')
    return failures


if __name__ == '__main__':
    failures = check()
    if failures:
        raise SystemExit('\n'.join(failures))
    print('PASS: shipped text is UTF-8 without known mojibake signatures.')
