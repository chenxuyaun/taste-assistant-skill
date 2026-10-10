"""测试公共设施：把 skill 目录加入 sys.path，并为每个测试提供隔离的临时 SQLite。"""
import os
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "taste_test.db"
    if os.path.exists(db_file):
        os.remove(db_file)
    monkeypatch.setenv("TASTE_DB_PATH", str(db_file))
    from storage import db
    db.init()
    yield
