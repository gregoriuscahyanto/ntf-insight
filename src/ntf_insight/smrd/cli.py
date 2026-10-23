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
    sub.add_parser("gui", help="Air-gapped PySide6 SMR-D workspace without Softing")
    add = sub.add_parser("add")
    add.add_argument("file", type=Path)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("file", type=Path)
    for name in ("preview", "import-xml"):
        p = sub.add_parser(name)
        p.add_argument("file", type=Path)
        p.add_argument("--skip-dtcs", action="store_true")
    offline_cmd = sub.add_parser("offline-convert")
    offline_cmd.add_argument("file", type=Path)
    offline_cmd.add_argument("--xml", type=Path, action="append", default=None,
                             help="Existing local XML; repeat for several exports")
    offline_cmd.add_argument("--out", type=Path)
    offline_cmd.add_argument("--remember", action="store_true",
                             help="Remember XML links locally by SMR-D SHA256")
    offline_import = sub.add_parser("offline-import")
    offline_import.add_argument("file", type=Path)
    smrd2xml = sub.add_parser(
        "smrd2xml", help="Use the user's local external Smrd2Xml.exe on Windows"
    )
    smrd2xml.add_argument("file", type=Path)
    smrd2xml.add_argument("--runtime-dir", type=Path)
    smrd2xml.add_argument("--ecu", help="ECU identifier (default: filename guess)")
    smrd2xml.add_argument(
        "--mode", choices=("ECU", "DTCSXML", "COMPAR", "CANMODEL"),
        action="append", dest="modes",
    )
    smrd2xml.add_argument("--timeout", type=int, default=180)
    smrd2xml.add_argument("--remember", action="store_true")
    smrd2xml.add_argument("--dry-run", action="store_true")
    for name in ("native-doctor", "native-prepare"):
        config_cmd = sub.add_parser(name)
        config_cmd.add_argument("--runtime-dir", type=Path)
        if name == "native-prepare":
            config_cmd.add_argument("--apply", action="store_true")
    recovery = sub.add_parser("native-restore-config")
    recovery.add_argument("--runtime-dir", type=Path)
    recovery.add_argument("--source-zip", type=Path, required=True)
    recovery.add_argument("--apply", action="store_true")
    native_capabilities_cmd = sub.add_parser("native-capabilities")
    native_capabilities_cmd.add_argument("--runtime-dir", type=Path)
    native_probe_cmd = sub.add_parser("native-probe")
    native_probe_cmd.add_argument("--runtime-dir", type=Path)
    project_test_cmd = sub.add_parser("native-project-test")
    project_test_cmd.add_argument("file", type=Path)
    project_test_cmd.add_argument("--runtime-dir", type=Path)
    project_test_cmd.add_argument("--timeout", type=int, default=120)
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
    elif args.cmd == "gui":
        from ntf_insight.smrd.offline_gui import main as offline_gui_main

        return offline_gui_main(
            ["--data-dir", str(args.data_dir)] if args.data_dir else []
        )
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
    elif args.cmd == "offline-convert":
        import json

        from ntf_insight.smrd.offline_convert import offline_convert

        report = offline_convert(
            args.file, xml_files=args.xml, data_dir=args.data_dir,
            output=args.out, remember=args.remember,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["total_references"]:
            print(
                "HINWEIS: Nur SMR-D-Metadaten. Der geschuetzte binaere Payload "
                "ist nicht decodiert; fuer DTCs vorhandene XML-Exporte "
                "mit --xml angeben."
            )
    elif args.cmd == "smrd2xml":
        import json

        from ntf_insight.smrd.smrd2xml_runner import (
            DEFAULT_MODES,
            run_smrd2xml,
        )

        report = run_smrd2xml(
            args.file, runtime_dir=args.runtime_dir,
            data_dir=args.data_dir, ecu=args.ecu,
            modes=tuple(args.modes) if args.modes else DEFAULT_MODES,
            timeout=args.timeout, remember=args.remember,
            dry_run=args.dry_run,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if not args.dry_run and not report.get("total_references"):
            print(
                "Keine indexierbaren ECU-/DTC-XML-Referenzen erzeugt. "
                "Siehe Modus-Logs; kein DuckDB-Import ausgefuehrt."
            )
    elif args.cmd == "offline-import":
        from ntf_insight.smrd.offline_convert import import_offline_bundle

        print(
            "Gespeicherte Offline-Referenzen:",
            import_offline_bundle(args.file, data_dir=args.data_dir),
        )
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
    elif args.cmd == "native-capabilities":
        import json

        from ntf_insight.smrd.native_export import native_capabilities

        print(json.dumps(
            native_capabilities(runtime_dir=args.runtime_dir, data_dir=args.data_dir),
            ensure_ascii=False, indent=2,
        ))
    elif args.cmd == "native-probe":
        from ntf_insight.smrd.native_export import native_probe

        print(native_probe(runtime_dir=args.runtime_dir, data_dir=args.data_dir))
    elif args.cmd == "native-project-test":
        from ntf_insight.smrd.native_export import native_project_test

        print(native_project_test(
            args.file, runtime_dir=args.runtime_dir,
            data_dir=args.data_dir, timeout=args.timeout,
        ))
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
