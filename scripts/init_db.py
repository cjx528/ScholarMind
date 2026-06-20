"""Initialize the local ScholarMind database."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def init_database() -> None:
    from packages.config import get_settings
    from packages.storage.db import run_migrations

    settings = get_settings()
    run_migrations()
    print(f"Database initialized: {settings.database_url}")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    init_database()
