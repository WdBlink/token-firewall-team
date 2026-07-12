from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from .schema import canonical_json_bytes
from .state import atomic_write_json


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_run_snapshot(run_dir: Path | str, archive_path: Path | str) -> dict[str, Any]:
    source = Path(run_dir).resolve()
    destination = Path(archive_path).resolve()
    if not source.is_dir():
        raise ValueError(f"run snapshot source is not a directory: {source}")
    if destination.is_relative_to(source):
        raise ValueError("snapshot archive must be outside the run directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"snapshot archive already exists: {destination}")
    files: list[dict[str, Any]] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"snapshot refuses symbolic link: {path}")
        if path.is_file():
            files.append({
                "path": path.relative_to(source).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            })
    manifest = {
        "schema": "token-firewall/run-snapshot-manifest@0.1",
        "source_name": source.name,
        "files": files,
        "dataset_sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
    }
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in files:
            archive.write(source / item["path"], item["path"])
        archive.writestr("SNAPSHOT-MANIFEST.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    receipt = {
        **manifest,
        "archive": str(destination),
        "archive_sha256": _sha256(destination),
        "archive_bytes": destination.stat().st_size,
    }
    atomic_write_json(destination.with_suffix(destination.suffix + ".receipt.json"), receipt)
    return receipt


def verify_run_snapshot(archive_path: Path | str) -> dict[str, Any]:
    archive_path = Path(archive_path).resolve()
    receipt_path = archive_path.with_suffix(archive_path.suffix + ".receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    findings: list[str] = []
    if _sha256(archive_path) != receipt["archive_sha256"]:
        findings.append("archive_sha256 mismatch")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            embedded = json.loads(archive.read("SNAPSHOT-MANIFEST.json"))
            if embedded["dataset_sha256"] != receipt["dataset_sha256"]:
                findings.append("embedded manifest differs from receipt")
            for item in embedded["files"]:
                data = archive.read(item["path"])
                if hashlib.sha256(data).hexdigest() != item["sha256"] or len(data) != item["bytes"]:
                    findings.append(f"payload mismatch: {item['path']}")
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        findings.append(f"archive unreadable: {exc}")
    return {"ok": not findings, "findings": findings, "archive": str(archive_path)}
