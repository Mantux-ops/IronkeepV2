"""
Fetch the latest ao-bin-dumps item snapshot into data/albion/source/.

This script requires an internet connection and is meant to be run explicitly
by a developer when the source data needs to be updated.  Production runtime
never calls this script.

Usage
-----
  python scripts/fetch_albion_snapshot.py [--output data/albion/source]

After running, execute:
  python scripts/import_albion_catalog.py
  python scripts/import_albion_catalog.py --check
  git add data/albion/source/ app/albion/data/items_t7_t8.json
  git commit -m "chore: refresh albion item catalog snapshot"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ITEMS_TXT_URL = (
    "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt"
)
COMMITS_API_URL = (
    "https://api.github.com/repos/ao-data/ao-bin-dumps/commits"
    "?path=formatted/items.txt&per_page=1"
)

DEFAULT_OUTPUT_DIR = _REPO_ROOT / "data" / "albion" / "source"
SNAPSHOT_FILENAME = "items_snapshot.txt"
METADATA_FILENAME = "source_metadata.json"
CATALOG_SCHEMA_VERSION = 2


def _fetch_text(url: str) -> bytes:
    print(f"  GET {url}")
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


def _latest_commit_sha(path_in_repo: str = "formatted/items.txt") -> str | None:
    url = (
        f"https://api.github.com/repos/ao-data/ao-bin-dumps/commits"
        f"?path={path_in_repo}&per_page=1"
    )
    try:
        raw = _fetch_text(url)
        commits = json.loads(raw)
        if commits:
            return commits[0]["sha"]
    except Exception as exc:
        print(f"  WARNING: could not fetch commit SHA: {exc}")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write snapshot files (default: data/albion/source/)",
    )
    args = parser.parse_args(argv)

    out_dir: Path = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching ao-bin-dumps item snapshot …")
    raw_items = _fetch_text(ITEMS_TXT_URL)
    sha256 = hashlib.sha256(raw_items).hexdigest()
    print(f"  SHA-256 : {sha256}")
    print(f"  Size    : {len(raw_items):,} bytes")

    commit_sha = _latest_commit_sha()
    print(f"  Commit  : {commit_sha or 'unknown'}")

    snapshot_path = out_dir / SNAPSHOT_FILENAME
    snapshot_path.write_bytes(raw_items)
    print(f"  Written : {snapshot_path}")

    metadata = {
        "source": "ao-bin-dumps",
        "source_repository": "https://github.com/ao-data/ao-bin-dumps",
        "source_file": "formatted/items.txt",
        "source_commit": commit_sha,
        "source_commit_date": None,
        "source_fetched_date": date.today().isoformat(),
        "source_sha256": sha256,
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "notes": [
            "source_commit is the latest commit that touched formatted/items.txt.",
            "source_sha256 is the SHA-256 of the downloaded formatted/items.txt file.",
            "Run scripts/import_albion_catalog.py to regenerate app/albion/data/items_t7_t8.json.",
            "Run scripts/import_albion_catalog.py --check to verify the catalog is up to date.",
        ],
    }
    metadata_path = out_dir / METADATA_FILENAME
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"  Written : {metadata_path}")

    print()
    print("Next steps:")
    print("  python scripts/import_albion_catalog.py")
    print("  python scripts/import_albion_catalog.py --check")
    print("  git add data/albion/source/ app/albion/data/items_t7_t8.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
