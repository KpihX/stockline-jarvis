"""pytest setup: a throwaway SQLite file (never the live ERP database) and the repo's seed when it exists.

    cd apps/backend && uv run pytest -q
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
if (REPO / "data" / "seed" / "meta.json").exists():
    os.environ["DATA_DIR"] = str(REPO / "data")
sys.path.insert(0, str(BACKEND))
