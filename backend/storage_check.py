"""Read-only Sheets readiness check; opt-in creation of missing tabs.

python -m backend.storage_check
python -m backend.storage_check --seed-missing
"""
import argparse

from .google_sheets import SheetsStore
from .storage import StorageError, TABLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-missing", action="store_true",
                        help="Create missing app tabs from local CSVs; never overwrite existing tabs.")
    args = parser.parse_args()
    try:
        store = SheetsStore.from_config()
        found = store.resolve(require_all=False)
        missing = [name for name in TABLES if name not in found]
        for name, prop in found.items():
            print(f"{name} -> {prop['title']}")
        if args.seed_missing:
            print("Created: " + (", ".join(store.seed_missing()) or "none"))
        elif missing:
            print("Missing tables: " + ", ".join(missing))
            print("Check GOOGLE_SHEETS_TAB_MAP first. Use --seed-missing only to create genuinely missing tables.")
            return 1
        tables = store.read_all()
        for name, (_, rows) in tables.items():
            print(f"Validated {name}: {len(rows)} rows")
        print("Read/schema check passed. No existing worksheet data was overwritten.")
        return 0
    except StorageError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
