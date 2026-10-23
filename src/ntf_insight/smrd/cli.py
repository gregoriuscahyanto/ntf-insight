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
    for name in ("native-doctor", "native-prepare"):
        config_cmd = sub.add_parser(name)
        config_cmd.add_argument("--runtime-dir", type=Path)
        if name == "native-prepare":
            config_cmd.add_argument("--apply", action="store_true")
    recovery = sub.add_parser("native-restore-config")
    recovery.add_argument("--runtime-dir", type=Path)
    recovery.add_argument("--source-zip", type=Path, required=True)
    recovery.add_argument("--apply", action="store_true")
    native_probe_cmd = sub.add_parser("native-probe")
    native_probe_cmd.add_argument("--runtime-dir", type=Path)
    native_export_cmd = sub.add_parser("native-export")
    native_export_cmd.add_argument("file", type=Path)
    native_export_cmd.add_argument("--runtime-dir", type=Path)
    native_export_cmd.add_argument("--out", type=Path)
    native_export_cmd.add_argument("--timeout", type=int, default=240)
    native_export_cmd.add_argument("--import-result", action="store_true")
    for name in ("native-preview", "native-import"):
        native_cmd = sub.add_parser(name)
        native_cmd.add_argument("file", type=Path)
        native_cmd.add_argument("--query", default="")
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
    elif args.cmd in ("native-doctor", "native-prepare"):
        import json

        from ntf_insight.smrd.runtime_config import (
            diagnose_native_runtime,
            prepare_native_runtime,
        )

        runtime = args.runtime_dir or library.root / "runtime" / "SMRxView"
        if args.cmd == "native-doctor":
            report = diagnose_native_runtime(runtime)
        else:
            report = prepare_native_runtime(
                runtime, data_dir=args.data_dir, apply=args.apply,
            )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.cmd == "native-restore-config":
        import json

        from ntf_insight.smrd.runtime_config import recover_native_runtime_configs

        runtime = args.runtime_dir or library.root / "runtime" / "SMRxView"
        print(json.dumps(recover_native_runtime_configs(
            runtime, args.source_zip, data_dir=args.data_dir, apply=args.apply,
        ), ensure_ascii=False, indent=2))
    elif args.cmd == "native-probe":
        from ntf_insight.smrd.native_export import native_probe

        print(native_probe(runtime_dir=args.runtime_dir, data_dir=args.data_dir))
    elif args.cmd == "native-export":
        from ntf_insight.smrd.native_export import export_native_dtcs

        output, count = export_native_dtcs(
            args.file,
            runtime_dir=args.runtime_dir,
            data_dir=args.data_dir,
            output_path=args.out,
            timeout=args.timeout,
        )
        print(f"Native DTS: {count} DTC-Details lokal exportiert: {output}")
        if args.import_result:
            from ntf_insight.smrd.native_details import import_native_details

            saved = import_native_details(output, data_dir=args.data_dir)
            print(f"NTF Insight: {saved} native DTC-Referenzen gespeichert")
    elif args.cmd in ("native-preview", "native-import"):
        from ntf_insight.smrd.native_details import (
            import_native_details,
            parse_native_details,
        )

        _, rows = parse_native_details(args.file)
        if args.cmd == "native-import":
            print(
                "NTF Insight: ",
                import_native_details(args.file, data_dir=args.data_dir),
                "native DTC-Referenzen gespeichert",
                sep="",
            )
        else:
            matched = [
                row for row in rows
                if not args.query
                or args.query.casefold() in (
                    row["reference"] + " " + row["label"] + " "
                    + str(row["data"].get("sdg_index", {}))
                ).casefold()
            ]
            print(f"Native DTS: {len(rows)} DTC-Details; {len(matched)} Suchtreffer")
            for row in matched[:25]:
                print(row["reference"], row["data"]["ecu"], row["data"]["variant"],
                      "level:", row["data"]["error_level"],
                      "repair:", bool(row["data"]["repair_action"]),
                      "causes:", bool(row["data"]["possible_causes"]))
    return 0
