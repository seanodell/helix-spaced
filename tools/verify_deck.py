"""Probe every card's own solution in a real hx and record what Helix produces.

The conformance fixture proves the *emulator* matches Helix on a fixed corpus.
This proves each *card* does what it claims: that running `start + keys` in real
Helix lands on the state the trainer grades against. Output feeds
tests/fixtures/deck_truth.json.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibrate import probe

from helix_spaced.deck import STATE, load_dir


def main() -> int:
    cards = [c for c in load_dir() if c.kind == STATE]
    cases = [{"text": c.text, "keys": c.start + c.keys, "id": c.id} for c in cards]
    workers = int(os.environ.get("HXCAL_WORKERS", "12"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(probe, cases))
    for case, result in zip(cases, results):
        result["id"] = case["id"]
    Path("tests/fixtures/deck_truth.json").write_text(json.dumps(results, indent=2))
    bad = [r for r in results if "ranges" not in r]
    skipped = len(load_dir()) - len(cards)
    print(f"{len(results)} state cards probed, {len(bad)} unreadable, "
          f"{skipped} keystroke cards skipped (nothing to probe)")
    for r in bad:
        print(f"  {r['id']}: {r.get('error')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
