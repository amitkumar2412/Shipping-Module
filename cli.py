"""CLI command implementations — one function per subcommand."""
import csv
import json
import logging
import os
import random
import time

from database import Store
from scraper import MarineTrafficClient, ScrapeError

log = logging.getLogger("tracker")


def scrape_all(store: Store, client: MarineTrafficClient):
    """Scrape every active ship once and persist results."""
    ships = store.active_ships()
    if not ships:
        log.warning("Watch list is empty. Add ships with: python main.py add <ship_id>")
        return
    ok = 0
    for i, ship_id in enumerate(ships):
        try:
            data = client.fetch_vessel(ship_id)
            new_pos = store.save(ship_id, data)
            p = data["position"] or {}
            log.info(
                "%s %s | %s | lat=%s lon=%s spd=%s | %s",
                ship_id, data["general"].get("name"),
                p.get("navigationalStatus"), p.get("lat"), p.get("lon"), p.get("speed"),
                "NEW position" if new_pos else "position unchanged",
            )
            result = store.latest(ship_id)
            flat_row = {}
            flat_row.update({f"vessel_{k}": v for k, v in (result["vessel"] or {}).items()})
            flat_row.update({f"position_{k}": v for k, v in (result["position"] or {}).items()})
            flat_row.update({f"voyage_{k}": v for k, v in (result["voyage"] or {}).items()})
            store.upsert_mainshipdata(flat_row)
            log.info("%s synced to mainshipdata", ship_id)
            ok += 1
        except (ScrapeError, Exception) as e:
            log.error("%s failed: %s", ship_id, e)
            store.log_error(ship_id, e)
        if i < len(ships) - 1:
            time.sleep(random.uniform(3, 8))
    log.info("Done: %d/%d ships scraped", ok, len(ships))


def cmd_add(store: Store, args):
    for sid in args.ship_ids:
        store.add_ship(sid)
    print("Tracking:", store.active_ships())


def cmd_remove(store: Store, args):
    for sid in args.ship_ids:
        store.remove_ship(sid)
    print("Tracking:", store.active_ships())


def cmd_list(store: Store, _args):
    for row in store.list_all_ships():
        print(row)


def cmd_run(store: Store, args):
    client = MarineTrafficClient()
    while True:
        scrape_all(store, client)
        if not args.loop:
            break
        wait = args.loop * 60 + random.uniform(-60, 60)
        log.info("Next run in %.1f minutes", wait / 60)
        time.sleep(max(wait, 60))


def cmd_show(store: Store, args):
    ship_ids = args.ship_ids if args.ship_ids else store.active_ships()
    if not ship_ids:
        log.warning("No ships tracked yet. Add ships with: python main.py add <ship_id>")

    results = []
    client = None
    for sid in ship_ids:
        result = store.latest(sid)
        if result["vessel"] is None:
            log.info("No stored data for %d — fetching live from MarineTraffic…", sid)
            if client is None:
                client = MarineTrafficClient()
            try:
                data = client.fetch_vessel(sid)
                store.add_ship(sid)
                store.save(sid, data)
                result = store.latest(sid)
            except ScrapeError as e:
                log.error("Failed to fetch ship %d: %s", sid, e)
        results.append(result)

    if args.csv_out:
        _write_csv(store, results, args.csv_out)
    else:
        for r in results:
            print(json.dumps(r, indent=2, ensure_ascii=False, default=str))


def _write_csv(store: Store, results: list, csv_path: str):
    def flat(d, prefix):
        return {f"{prefix}_{k}": v for k, v in (d or {}).items()}

    rows = []
    for r in results:
        row = {}
        row.update(flat(r["vessel"], "vessel"))
        row.update(flat(r["position"], "position"))
        row.update(flat(r["voyage"], "voyage"))
        rows.append(row)

    if not rows:
        print("No data to write.")
        return

    fieldnames = list(rows[0].keys())
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {len(rows)} ship(s) to {csv_path}")
    except PermissionError:
        log.warning("Cannot write %s — file may be open in another program. Skipping CSV.", csv_path)

    for row in rows:
        store.upsert_mainshipdata(row)
    print(f"Synced {len(rows)} ship(s) to mainshipdata table")


def cmd_track(store: Store, args):
    points = store.track(args.ship_id, since=args.since)
    if not points:
        print(f"No position history for {args.ship_id}")
        return

    if args.geojson:
        feature = {
            "type": "Feature",
            "properties": {"ship_id": args.ship_id},
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [p["lon"], p["lat"]] for p in points
                    if p["lon"] is not None and p["lat"] is not None
                ],
            },
        }
        with open(args.geojson, "w", encoding="utf-8") as f:
            json.dump(feature, f, ensure_ascii=False)
        print(f"Wrote {len(points)} point(s) to {args.geojson}")
    else:
        print(json.dumps(points, indent=2, ensure_ascii=False, default=str))


def cmd_export(store: Store, args):
    os.makedirs(args.out_dir, exist_ok=True)
    for table in ("ships", "vessels", "shippingport", "positions", "voyages", "scrape_log", "mainshipdata"):
        cols, rows = store.export_table(table)
        path = os.path.join(args.out_dir, f"{table}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        print("wrote", path)
