"""MarineTraffic vessel tracker.

  python main.py add 314687 [more ids...]     add ships to the watch list
  python main.py remove 314687                stop tracking a ship (history is kept)
  python main.py list                         show the watch list
  python main.py run                          scrape every active ship once
  python main.py run --loop 60                scrape every 60 minutes, forever
  python main.py show                         print latest data for ALL tracked ships
  python main.py show 314687 123456           print latest data for specific ship IDs
  python main.py show --csv                   export latest data for all ships to CSV + mainshipdata table
  python main.py show 314687 --csv            export latest data for specific ships to CSV
  python main.py track 314687                 print position history (route) for one ship
  python main.py track 314687 --geojson       export route as GeoJSON LineString (route.geojson)
  python main.py export [out_dir]             export every table to CSV

Credentials for PostgreSQL are read from environment variables (or a .env file):
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""
import argparse
import logging

from dotenv import load_dotenv

load_dotenv()

from database import Store
from cli import cmd_add, cmd_remove, cmd_list, cmd_run, cmd_show, cmd_track, cmd_export


def build_parser():
    ap = argparse.ArgumentParser(description="MarineTraffic vessel tracker")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add ships to the watch list")
    a.add_argument("ship_ids", nargs="+", type=int)

    r = sub.add_parser("remove", help="stop tracking a ship (history is kept)")
    r.add_argument("ship_ids", nargs="+", type=int)

    sub.add_parser("list", help="show the watch list")

    run = sub.add_parser("run", help="scrape all active ships")
    run.add_argument("--loop", type=float, metavar="MINUTES", help="repeat every N minutes")

    s = sub.add_parser("show", help="print or export latest data")
    s.add_argument("ship_ids", nargs="*", type=int, help="ship IDs (omit for all tracked ships)")
    s.add_argument(
        "--csv", dest="csv_out", metavar="FILE", nargs="?", const="ships_latest.csv",
        help="write output to CSV instead of JSON (default file: ships_latest.csv)",
    )

    t = sub.add_parser("track", help="print or export position history (route) for one ship")
    t.add_argument("ship_id", type=int)
    t.add_argument("--since", type=int, metavar="EPOCH_TS", help="only positions at/after this unix timestamp")
    t.add_argument(
        "--geojson", metavar="FILE", nargs="?", const="route.geojson",
        help="write a GeoJSON LineString instead of JSON (default file: route.geojson)",
    )

    e = sub.add_parser("export", help="export every table to CSV files")
    e.add_argument("out_dir", nargs="?", default="export")

    return ap


COMMANDS = {
    "add":    cmd_add,
    "remove": cmd_remove,
    "list":   cmd_list,
    "run":    cmd_run,
    "show":   cmd_show,
    "track":  cmd_track,
    "export": cmd_export,
}


def main():
    args = build_parser().parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("tracker.log", encoding="utf-8"),
        ],
    )

    store = Store()
    COMMANDS[args.cmd](store, args)


if __name__ == "__main__":
    main()
