"""Command-line entrypoint; suitable for later PySide6 integration."""
from __future__ import annotations

import argparse
from pathlib import Path
from ntf_insight.smrd.library import SmrdLocalLibrary
from ntf_insight.smrd.importer import SmrdImportService
from ntf_insight.smrd.binary_header import inspect_smrd_header


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-only SMR-D library and XML reference parser")
    parser.add_argument("--data-dir", type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("where")
    sub.add_parser("list")
    add = sub.add_parser("add")
    add.add_argument("file", type=Path)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("file", type=Path)
    for name in ("preview", "import-xml"):
        p = sub.add_parser(name)
        p.add_argument("file", type=Path)
        p.add_argument("--skip-dtcs", action="store_true")
    args = parser.parse_args(argv)
    library = SmrdLocalLibrary(data_dir=args.data_dir)
    if args.cmd == "where":
        print(library.root)
    elif args.cmd == "list":
        for item in library.list_smrd():
            print(item["sha256"], item["path"])
    elif args.cmd == "add":
        print(library.add_smrd(args.file)["path"])
    elif args.cmd == "inspect":
        import json
        print(json.dumps(inspect_smrd_header(args.file), indent=2))
    elif args.cmd in ("preview", "import-xml"):
        service = SmrdImportService(data_dir=args.data_dir)
        if args.cmd == "preview":
            metadata, rows = service.preview(args.file, skip_dtcs=args.skip_dtcs)
            print(metadata, len(rows))
        else:
            print("Gespeicherte Referenzzeilen:", service.import_xml(args.file, skip_dtcs=args.skip_dtcs))
    return 0
