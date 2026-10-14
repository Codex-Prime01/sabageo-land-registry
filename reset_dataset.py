"""
Cleans the city dataset and loads it again, the right way.

What it does (only when you add --go):
  1. Takes out EVERY synthetic plot, including the old Maiduguri/Biu plots from the
     first dataset, and any photos attached to them.
  2. Writes a "removed" record in the ledger for each one, with the reason.
     The ledger is never edited or shortened, so the chain stays valid.
  3. Tidies the ledger: plots that were deleted earlier without a record get one now.
  4. Deletes regions that are not in the official list and have no plots left.
  5. Loads the 55 dataset plots again (11 cities x 5) at 18 m x 30 m.

Real field plots (NAUB pilot, client plots, test-area plots) are NOT touched,
unless you name them with --remove.

Use it like this:
  python reset_dataset.py                  shows what would happen, changes nothing
  python reset_dataset.py --go             does it
  python reset_dataset.py --go --remove SABA-BIU-RES-001 SABA-TST-RES-002
                                           also takes out those named plots
"""
import json
import sys

import psycopg

import ingest_cities
import main

OFFICIAL_REGIONS = {"NAUB", "LAG", "ABJ", "GMB", "KAN", "MDG", "BIU",
                    "IBD", "PHC", "BEN", "OWR", "ILR", "TST", "OTH"}
REASON = "Synthetic dataset reset: old data replaced by the 55-plot city dataset at 18 m x 30 m"


def latest_ledger(conn):
    """The latest ledger record for each title code: {code: payload dict}."""
    out = {}
    for code, payload in conn.execute("SELECT title_code, payload FROM ledger ORDER BY id").fetchall():
        out[code] = json.loads(payload)
    return out


def plan(conn, extra):
    synthetic = conn.execute(
        """
        SELECT p.title_code, p.region_code, COALESCE(p.label, '')
        FROM plots p WHERE p.source = 'synthetic' ORDER BY p.region_code, p.id
        """
    ).fetchall()
    named = []
    for code in extra:
        row = conn.execute(
            "SELECT title_code, region_code, COALESCE(label, ''), status FROM plots WHERE title_code = %s",
            (code,),
        ).fetchone()
        if not row:
            print(f"  (--remove {code}: no such plot, ignored)")
        elif row[3] == "reserved":
            print(f"  (--remove {code}: that is an empty pilot slot, ignored)")
        elif row[0] not in {s[0] for s in synthetic}:
            named.append(row[:3])
    field = conn.execute(
        """
        SELECT p.title_code, p.region_code, COALESCE(p.label, '')
        FROM plots p
        WHERE p.source <> 'synthetic' AND p.status = 'registered'
        ORDER BY p.region_code, p.id
        """
    ).fetchall()
    existing = {r[0] for r in conn.execute("SELECT title_code FROM plots").fetchall()}
    orphans = [c for c, d in latest_ledger(conn).items() if d.get("action") != "removed" and c not in existing]
    regions = conn.execute(
        "SELECT r.code, r.name, COUNT(p.id) FROM regions r LEFT JOIN plots p ON p.region_code = r.code "
        "GROUP BY r.code, r.name ORDER BY r.code"
    ).fetchall()
    return synthetic, named, field, orphans, regions


def show(synthetic, named, field, orphans, regions):
    by_region = {}
    for code, region, label in synthetic:
        by_region.setdefault(region, []).append(f"{code} ({label})" if label else code)
    print(f"\nSynthetic plots to take out: {len(synthetic)}")
    for region, items in by_region.items():
        print(f"  {region}: {len(items)}  " + ", ".join(items))
    if named:
        print(f"\nNamed plots to take out (--remove): {len(named)}")
        for code, region, label in named:
            print(f"  {code}  {region}  {label}")
    keep = [f for f in field if f[0] not in {n[0] for n in named}]
    print(f"\nReal field plots that will be KEPT: {len(keep)}")
    for code, region, label in keep:
        print(f"  {code}  {region}  {label}")
    if keep:
        print("  If any of these are leftovers from the old Maiduguri/Biu data, add them with --remove.")
    if orphans:
        print(f"\nLedger tidy-up (plots already gone, no removal record yet): {len(orphans)}")
        print("  " + ", ".join(orphans))
    extra = [r for r in regions if r[0] not in OFFICIAL_REGIONS]
    if extra:
        print("\nRegions not in the official list:")
        for code, name, n in extra:
            print(f"  {code}  {name}  ({n} plots now)")
    print("\nThen the 55 dataset plots (11 cities x 5, 18 m x 30 m) are loaded again.")


def run(go, extra):
    with psycopg.connect(main.DB) as conn:
        conn.execute("LOCK TABLE plots IN SHARE ROW EXCLUSIVE MODE")
        synthetic, named, field, orphans, regions = plan(conn, extra)
        show(synthetic, named, field, orphans, regions)
        if not go:
            print("\nNothing was changed. Run again with --go to do it.")
            return

        synthetic_codes = {s[0] for s in synthetic}
        for code, _, _ in synthetic + named:
            conn.execute("DELETE FROM photos WHERE title_code = %s", (code,))
            conn.execute("DELETE FROM plots WHERE title_code = %s", (code,))
            reason = REASON if code in synthetic_codes else "Removed by the administrator (old dataset leftover)"
            main.add_removal_record(conn, code, reason)
        for code in orphans:
            main.add_removal_record(conn, code, "Ledger tidy-up: this plot had already been deleted")

        for code, name, _ in regions:
            if code in OFFICIAL_REGIONS:
                continue
            left = conn.execute("SELECT COUNT(*) FROM plots WHERE region_code = %s", (code,)).fetchone()[0]
            if left:
                print(f"Kept region {code} ({name}): it still has {left} plots")
                continue
            try:
                with conn.transaction():  # a savepoint, so one failure does not undo everything
                    conn.execute("DELETE FROM regions WHERE code = %s", (code,))
                print(f"Deleted region {code} ({name})")
            except psycopg.Error:
                print(f"Kept region {code} ({name}): something else still uses it")

        print()
        added, skipped = ingest_cities.run(conn)
        if added != 55:
            raise SystemExit(f"Expected 55 plots but loaded {added}. Nothing was changed.")
    print("\nAll done. Open /ledger/verify (or tap Verify ledger) to check the chain.")


if __name__ == "__main__":
    args = sys.argv[1:]
    go = "--go" in args
    extra = []
    if "--remove" in args:
        extra = [a.strip().upper() for a in args[args.index("--remove") + 1:] if not a.startswith("--")]
    run(go, extra)
