import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own empty database and file store."""
    monkeypatch.setenv("BLM_DATA_DIR", str(tmp_path / "data"))
    from bl_manager import db

    db.init_db()
    yield tmp_path
