"""
Versioned result file path and atomic write tests.
"""

import json
import tempfile

import pytest

from app.utils.file_utils import FileManager
from app.worker.processor import _build_result_path


@pytest.fixture
def nfs_root(monkeypatch):
    root = tempfile.mkdtemp(prefix="sqlfluff_nfs_")
    monkeypatch.setenv("NFS_SHARE_ROOT_PATH", root)
    FileManager._instance = None
    FileManager._initialized = False
    yield root
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    FileManager._instance = None
    FileManager._initialized = False


@pytest.fixture
def file_manager(nfs_root):
    return FileManager(nfs_root=nfs_root)


class TestResultPath:
    def test_versioned_path_includes_lease_token(self):
        path = _build_result_path("job-1", "task-1", "abc123token")
        assert path == "results/job-1/task-1/abc123token.json"

    def test_no_lease_uses_placeholder(self):
        path = _build_result_path("job-1", "task-1", None)
        assert path == "results/job-1/task-1/no-lease.json"


class TestAtomicWriteAndCleanup:
    def test_write_json_file_atomic_uses_replace(self, file_manager):
        fm = file_manager
        rel = "results/job-1/task-1/token-a.json"
        data = {"summary": {"total_violations": 0}}

        fm.write_json_file_atomic(rel, data)

        abs_path = fm.get_absolute_path(rel)
        assert abs_path.exists()
        assert not abs_path.with_suffix(abs_path.suffix + ".tmp").exists()
        loaded = json.loads(abs_path.read_text(encoding="utf-8"))
        assert loaded["summary"]["total_violations"] == 0

    def test_write_json_file_atomic_leaves_no_tmp_file(self, file_manager):
        fm = file_manager
        rel = "results/job-1/task-1/token-b.json"
        fm.write_json_file_atomic(rel, {"v": 1})

        abs_path = fm.get_absolute_path(rel)
        tmp_path = abs_path.with_suffix(abs_path.suffix + ".tmp")
        assert abs_path.exists()
        assert not tmp_path.exists()

    def test_cleanup_stale_result_files_keeps_current(self, file_manager):
        fm = file_manager
        keep = "results/job-1/task-1/current.json"
        stale = "results/job-1/task-1/old-token.json"

        fm.write_json_file_atomic(keep, {"keep": True})
        fm.write_json_file_atomic(stale, {"keep": False})

        removed = fm.cleanup_stale_result_files("job-1", "task-1", keep)

        assert removed == 1
        assert fm.get_absolute_path(keep).exists()
        assert not fm.get_absolute_path(stale).exists()
