"""Check UI text, backend messages, rule files and docs against content-rules.yaml.

Run from the repository root: python scripts/check_content.py [--summary]
Exits 1 when any sentence uses a banned phrase or is prose that names nothing and counts nothing.
"""
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend')]

from app.content.check import scan  # noqa: E402


def main():
    violations = scan(ROOT)
    if '--summary' in sys.argv:
        for key, n in Counter((v.kind, v.file) for v in violations).most_common():
            print(n, *key)
    else:
        for v in sorted(violations, key=lambda v: (v.file, v.line)):
            print(v.render())
    print(f'{len(violations)} violation(s) in {len({v.file for v in violations})} file(s)')
    return 1 if violations else 0


if __name__ == '__main__':
    raise SystemExit(main())
