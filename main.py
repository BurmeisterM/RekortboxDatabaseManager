"""GUI entry point, plus a read-only diagnostic for installation checks."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Rekordbox Database Manager")
    parser.add_argument("database", nargs="?", help="Pfad zur master.db")
    parser.add_argument("--diagnose", metavar="MASTER.DB", help="Datenbank ohne Oberfläche nur lesend prüfen")
    parser.add_argument("--report", metavar="JSON", help="Diagnose in eine JSON-Datei schreiben")
    args = parser.parse_args()
    if args.report and not args.diagnose:
        parser.error("--report benötigt --diagnose")
    if args.diagnose:
        from rekordbox_manager.database import load_library
        try:
            library = load_library(args.diagnose)
            report = {"ok": True, "tracks": len(library.tracks), "duplicate_groups": len(library.groups),
                      "encrypted": library.encrypted, "covers_found": sum(bool(t.cover) for t in library.tracks)}
        except Exception as exc:
            report = {"ok": False, "error": str(exc)}
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.report:
            Path(args.report).write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0 if report["ok"] else 1
    from rekordbox_manager.ui import main as gui_main
    return gui_main([args.database] if args.database else [])


if __name__ == "__main__":
    raise SystemExit(main())
