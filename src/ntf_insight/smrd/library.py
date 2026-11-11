"""Local-only, ECU-independent SMR-D file library.

Existing files under ~/.ntf-insight/smrd/originale are detected by SHA-256
without renaming. No files are uploaded, deleted, or executed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def data_root(data_dir: Path | None = None) -> Path:
    return Path(data_dir).expanduser() if data_dir else Path(os.getenv("NTF_INSIGHT_DATA_DIR") or (Path.home() / ".ntf-insight")).expanduser()


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1048576), b""):
            sha.update(chunk)
    return sha.hexdigest()


class SmrdLocalLibrary:
    def __init__(self, *, data_dir: Path | None = None):
        self.root = data_root(data_dir) / "smrd"
        self.originals = self.root / "originale"
        self.exports = self.root / "exporte"
        self.manifests = self.root / "manifeste"

    def _ensure(self) -> None:
        for directory in (self.root.parent, self.root, self.originals, self.exports, self.manifests):
            if directory.is_symlink():
                raise ValueError(f"Unsicherer symbolischer Link: {directory}")
            directory.mkdir(parents=True, exist_ok=True)

    def list_smrd(self) -> list[dict]:
        """Find manually placed files as well as previously imported originals."""
        if self.originals.is_symlink():
            raise ValueError("Unsicherer symbolischer Link im SMR-D-Ordner")
        if not self.originals.exists():
            return []
        return [
            {"sha256": digest(p), "path": p, "filename": p.name}
            for p in sorted(self.originals.iterdir())
            if p.is_file() and not p.is_symlink() and p.suffix.lower() == ".smr-d"
        ]

    def add_smrd(self, source: Path) -> dict:
        source = Path(source).expanduser()
        if source.is_symlink() or not source.is_file() or source.suffix.lower() != ".smr-d":
            raise ValueError("SMR-D muss eine regulaere .smr-d-Datei sein")
        self._ensure()
        checksum = digest(source)
        existing = next((item for item in self.list_smrd() if item["sha256"] == checksum), None)
        if existing is not None:
            return existing
        target = self.originals / f"{checksum}.smr-d"
        with tempfile.NamedTemporaryFile(dir=self.originals, delete=False) as stream:
            staged = Path(stream.name)
            try:
                with source.open("rb") as src:
                    shutil.copyfileobj(src, stream)
            except BaseException:
                staged.unlink(missing_ok=True)
                raise
        try:
            if digest(staged) != checksum:
                raise ValueError("SHA-256 nach dem Kopieren unterschiedlich")
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        manifest = self.manifests / f"{checksum}.json"
        manifest.write_text(json.dumps({"sha256": checksum, "original_name": source.name,
                                        "path": str(target.relative_to(self.root))},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        return {"sha256": checksum, "path": target, "filename": target.name}
