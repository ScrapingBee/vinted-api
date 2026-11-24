"""Price research for one Vinted search, past the 960 listing ceiling.

A Vinted catalog search stops at page 10 (10 x 96 = 960 tiles), however many
listings match. This script splits one query into price bands with the
catalog's own price_from / price_to filters, walks each band, drops repeats,
and summarises asking prices by condition and by size.

Usage:
    export SCRAPINGBEE_API_KEY=...
    python vinted_price_bands.py "levis 501" --bands 0 8 12 18 25 40 400 \
        --filter "brand_ids[]=10" --pages 4 --csv levis_bands.csv

Cost: 1 credit per catalog page, so at most (bands x pages) credits.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict

from vinted_client import MAX_PAGES, PER_PAGE, Listing, VintedClient


def quartiles(xs: list[float]) -> tuple[float, float, float]:
    if len(xs) < 2:
        v = xs[0] if xs else float("nan")
        return v, v, v
    q = statistics.quantiles(xs, n=4, method="inclusive")
    return q[0], q[1], q[2]


def table(title: str, groups: dict[str, list[Listing]], top: int | None = None) -> None:
    print(f"\n{title}")
    print(f"  {'':22} {'n':>5} {'p25':>8} {'median':>8} {'p75':>8} {'median total':>13}")
    order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for name, rows in order[:top]:
        p25, med, p75 = quartiles(sorted(r.price for r in rows if r.price is not None))
        tot = statistics.median(r.total_price for r in rows if r.total_price is not None)
        print(f"  {name[:22]:22} {len(rows):>5} {p25:>8.2f} {med:>8.2f} {p75:>8.2f} {tot:>13.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Split a Vinted search into price bands and summarise prices")
    ap.add_argument("query")
    ap.add_argument("--bands", type=float, nargs="+", default=[0, 10, 20, 40, 1000],
                    help="band edges; each band is price_from=edge[i], price_to=edge[i+1]")
    ap.add_argument("--pages", type=int, default=MAX_PAGES, help="max pages per band (1 credit each)")
    ap.add_argument("--currency", default="GBP")
    ap.add_argument("--order", default="newest_first")
    ap.add_argument("--filter", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--domain", default="www.vinted.co.uk")
    ap.add_argument("--csv")
    a = ap.parse_args()

    key = os.environ.get("SCRAPINGBEE_API_KEY")
    if not key:
        sys.exit("set SCRAPINGBEE_API_KEY")
    client = VintedClient(key, a.domain)
    extra = [tuple(f.split("=", 1)) for f in a.filter]

    found: dict[int, Listing] = {}
    band_of: dict[int, str] = {}
    repeats = outside = 0
    edges = list(zip(a.bands, a.bands[1:]))
    for n, (lo, hi) in enumerate(edges):
        name = f"{lo:g}-{hi:g}"
        # Vinted treats both price_from and price_to as inclusive, so a listing
        # at exactly 12.00 would come back in the 8-12 band and the 12-18 band.
        # Every band except the last stops one penny short of its upper edge.
        top = hi if n == len(edges) - 1 else round(hi - 0.01, 2)
        got = pages = last = dup = 0
        has_next = True
        while has_next and pages < min(a.pages, MAX_PAGES):
            pages += 1
            rows, has_next = client.search_page(a.query, pages, order=a.order, price_from=lo, price_to=top,
                                                currency=a.currency, extra=extra)
            last = len(rows)
            for r in rows:
                if r.price is not None and not (lo <= r.price <= top):
                    outside += 1  # should not happen; counted so it would show up
                if r.id in found:
                    dup += 1
                    continue
                found[r.id] = r
                band_of[r.id] = name
                got += 1
            if len(rows) < PER_PAGE:
                break
        # page 10 carries a disabled Next link even when more listings match,
        # so a full page 10 is the sign that the band was cut off
        if pages == MAX_PAGES and last == PER_PAGE:
            state = "hit the 10 page ceiling, split this band"
        elif has_next:
            state = f"more pages left (stopped at --pages {a.pages})"
        else:
            state = "complete"
        repeats += dup
        print(f"band {name:>9} {a.currency}: {got:>4} new, {dup:>3} repeats, {pages:>2} pages, {state}",
              file=sys.stderr)

    rows = list(found.values())
    print(f"\n{len(rows)} unique listings, {repeats} repeats dropped, {outside} outside their band, "
          f"{client.credits} credits", file=sys.stderr)
    if not rows:
        return

    prices = sorted(r.price for r in rows if r.price is not None)
    p25, med, p75 = quartiles(prices)
    print(f"\n'{a.query}' on {a.domain}: {len(rows)} listings, asking price p25 {p25:.2f}, "
          f"median {med:.2f}, p75 {p75:.2f} {a.currency}")

    by_cond: dict[str, list[Listing]] = defaultdict(list)
    by_size: dict[str, list[Listing]] = defaultdict(list)
    for r in rows:
        by_cond[r.condition or "?"].append(r)
        by_size[r.size or "no size"].append(r)
    table("By condition", by_cond)
    table("Most listed sizes", by_size, top=8)

    if a.csv:
        names = list(asdict(rows[0]).keys()) + ["band"]
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=names)
            w.writeheader()
            for r in rows:
                w.writerow({**asdict(r), "band": band_of[r.id]})
        print(f"\nwrote {a.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
