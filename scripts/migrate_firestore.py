"""Firestore export → PostgreSQL loader (API-19). See app/modules/hub/load.py.

uv run python scripts/migrate_firestore.py export.json [--dry-run]
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.hub.load import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
