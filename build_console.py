"""Build the operator console: template + run data -> docs/index.html.

This exists because the two drifted. Hosted-copy messaging was once
applied to the build output instead of the template, and the next rebuild
silently reverted it — the live page shipped a worse message for hours
without anything failing. One command, one source of truth.

    uv run python build_console.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "console_template.html"
DATA = ROOT / "results" / "console_data.json"
OUTPUTS = [ROOT / "docs" / "index.html", ROOT / "console.html"]

# Markers that must survive every build. Each one is a thing that has
# already been lost once, or would be silently wrong if it went missing.
REQUIRED = [
    "<title>Warrant Operator Console</title>",
    'id="v-queue"',
    'id="v-cleared"',
    'id="v-check"',
    'id="v-perf"',
    'id="v-how"',
    "hosted copy",              # the fallback message that got reverted
    "of the taxable base",      # statutory-charge basis, the 32% fix made visible
    '"queue":[',                # embedded run data actually injected
]

# Figures from superseded runs. If one of these reappears, the console is
# advertising a failure rate the system no longer has.
FORBIDDEN = ["20,881", "240 model calls"]


def main() -> int:
    template = TEMPLATE.read_text(encoding="utf-8")
    if "__DATA__" not in template:
        print(f"FAIL: {TEMPLATE.name} has no __DATA__ placeholder")
        return 1

    data = DATA.read_text(encoding="utf-8")
    json.loads(data)  # fail loudly on malformed data rather than shipping it
    out = template.replace("__DATA__", data)

    problems = [f"missing: {m!r}" for m in REQUIRED if m not in out]
    problems += [f"stale figure present: {m!r}" for m in FORBIDDEN if m in out]
    if problems:
        print("FAIL — not writing anything:")
        for p in problems:
            print("  -", p)
        return 1

    for path in OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out, encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}  ({len(out):,} bytes)")

    print(f"\nOK — {len(REQUIRED)} required markers present, no stale figures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
