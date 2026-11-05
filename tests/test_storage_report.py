import importlib.util
from pathlib import Path


def test_storage_report_counts_metadata_without_changing_or_exposing_data(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "storage_report.py"
    spec = importlib.util.spec_from_file_location("storage_report", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = {"output/book.epub": b"BOOK", "logs/sync.log": b"LOG",
            ".websync-replicas/replica.json": b"REPLICA", "sync_history.db": b"DB",
            "config.json": b'SECRET-API-KEY'}
    for name, value in data.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    report = module.storage_report(tmp_path)
    assert report["groups"]["epubs"] == {"files": 1, "bytes": 4}
    assert report["groups"]["replicas"] == {"files": 1, "bytes": 7}
    assert "SECRET" not in str(report)
    assert report["metadata_errors"] == 0
    assert {name: (tmp_path / name).read_bytes() for name in data} == data
