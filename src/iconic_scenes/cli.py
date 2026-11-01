"""iconic-scenes run [ids...] [--force] | copies [ids...] [--fresh] | report | export"""
import argparse
import sys

from . import export, pipeline, report


def main() -> None:
    ap = argparse.ArgumentParser(prog="iconic-scenes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="locate the lines and pick the stills")
    r.add_argument("ids", nargs="*", help="quote ids from data/quotes.csv (all by default)")
    r.add_argument("--force", action="store_true", help="redo quotes that already have a result")
    r.add_argument("--sidecar-only", action="store_true", help="only sidecar subtitle files (fast), no embedded track extraction")
    r.add_argument("--speech", action="store_true", help="fall back to local speech recognition when no subtitle track matches")
    c = sub.add_parser("copies", help="re-list the Plex copies of each film into its result (edition, duration, file)")
    c.add_argument("ids", nargs="*", help="quote ids (all by default)")
    c.add_argument("--fresh", action="store_true", help="ask Plex again instead of the work/plex/ cache")
    sub.add_parser("report", help="write data/iconic-scenes.csv and site/index.html from the results")
    sub.add_parser("export", help="write data/iconic-scenes.csv only")
    args = ap.parse_args()
    if args.cmd == "run":
        todo = [q for q in pipeline.quotes() if not args.ids or q["id"] in args.ids]
        for n, q in enumerate(todo, 1):
            res = pipeline.run_one(q, force=args.force, embedded=not args.sidecar_only, speech=args.speech)
            m = res.get("match") or {}
            print(f"[{n}/{len(todo)}] {q['id']}: {res['status']} {m.get('score', '')} {m.get('start', '')}", flush=True)
        report.write()
    elif args.cmd == "copies":
        todo = [q for q in pipeline.quotes() if not args.ids or q["id"] in args.ids]
        for q in todo:
            res = pipeline.refresh_copies(q, fresh=args.fresh)
            if res and res.get("file") and res.get("copy_id") is None:
                print(f"{q['id']}: the copy it was read from is no longer in Plex, rerun it: {res['file']}")
        print(report.write())
    elif args.cmd == "export":
        print(export.write())
    else:
        print(report.write())


if __name__ == "__main__":
    sys.exit(main())
