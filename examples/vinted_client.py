"""Read public Vinted catalog and item pages through ScrapingBee.

Two page types are used, both allowed by Vinted's robots.txt:

    /catalog?search_text=...   search results, 96 listings per page
    /items/<id>                one listing (JSON-LD plus the details list)

Seller profile pages live under /member/, which robots.txt disallows, so this
client never requests them. Everything seller related comes from the item page.

Usage:
    export SCRAPINGBEE_API_KEY=...
    python vinted_client.py search "levis 501" --pages 2 --csv levis.csv
    python vinted_client.py search "levis 501" --order price_low_to_high \
        --price-from 20 --price-to 40 --filter "status_ids[]=6" --json new.json
    python vinted_client.py item 10952746328 10951409620 --json items.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Iterator
from urllib.parse import urlencode

import requests

API = "https://app.scrapingbee.com/api/v1/"
DEFAULT_DOMAIN = "www.vinted.co.uk"
PER_PAGE = 96  # what the catalog grid renders server side
MAX_PAGES = 10  # the public catalog stops at page 10 (960 listings)

CURRENCY = {"£": "GBP", "€": "EUR", "$": "USD", "zł": "PLN", "Kč": "CZK"}

# Every selector below was read off the server-rendered HTML of vinted.co.uk.
CATALOG_RULES = {
    "page_title": "title",
    "items": {
        "selector": "div[data-testid='grid-item']",
        "type": "list",
        "output": {
            "box": {"selector": "div[data-testid^='product-item-id-'][class*='container']", "output": "@data-testid"},
            "href": {"selector": "a[data-testid$='--overlay-link']", "output": "@href"},
            "label": {"selector": "a[data-testid$='--overlay-link']", "output": "@title"},
            "brand": "p[data-testid$='--description-title']",
            "subtitle": "p[data-testid$='--description-subtitle']",
            "price": "span[data-testid$='--price-text']",
            "total": "span[data-testid='total-combined-price']",
            "favourites": "span[data-testid='favourite-count-text']",
            "image": {"selector": "img[data-testid$='--image--img']", "output": "@src"},
        },
    },
    "next": {"selector": "a[data-testid='catalog-pagination--next-page']", "output": "@href"},
    "next_disabled": {"selector": "a[data-testid='catalog-pagination--next-page']", "output": "@aria-disabled"},
}

ITEM_RULES = {
    "title": "h1",
    "ld": {"selector": "script[type='application/ld+json']", "output": "html"},
    "price": "div[data-testid='item-price']",
    "total": "div[data-testid='item-sidebar-price-container'] span[data-testid='total-combined-price']",
    "attributes": {
        "selector": "div[data-testid^='item-attributes-']",
        "type": "list",
        "output": {
            "key": {"selector": "div[data-testid^='item-attributes-']", "output": "@data-testid"},
            "value": "div[itemprop]",
        },
    },
    "description": "div[itemprop='description']",
    "shipping": "span[data-testid='item-shipping-banner-price']",
    "seller": "span[data-testid='profile-username']",
    "rating": {"selector": "div[role='group'][aria-label^='Member rated']", "output": "@aria-label"},
    "reviews": "div.web_ui__Rating__label",
    "last_seen": "span[data-testid='seller-last-logged-in']",
    "breadcrumbs": {"selector": "a[data-testid='breadcrumb']", "type": "list"},
    "photos": {"selector": "img[data-testid^='item-photo-'][data-testid$='--img']", "type": "list", "output": "@src"},
    "buy_button": "button[data-testid='item-buy-button']",
}


def money(text: str | None) -> tuple[float | None, str | None]:
    """'£11.20' -> (11.2, 'GBP'); '21,70 €' -> (21.7, 'EUR')."""
    if not text:
        return None, None
    cur = next((code for sym, code in CURRENCY.items() if sym in text), None)
    m = re.search(r"\d[\d.,\s]*", text)
    if not m:
        return None, cur
    num = m.group(0).strip().replace(" ", "")
    if re.search(r",\d{2}$", num):  # continental decimal comma
        num = num.replace(".", "").replace(",", ".")
    else:
        num = num.replace(",", "")
    return float(num), cur


@dataclass
class Listing:
    """One tile from the catalog grid."""

    id: int
    title: str
    brand: str | None
    size: str | None
    condition: str | None
    price: float | None
    total_price: float | None  # price plus the Vinted buyer fee, as shown on the tile
    currency: str | None
    favourites: int
    url: str
    image: str | None
    page: int
    position: int

    @classmethod
    def from_tile(cls, t: dict, base: str, page: int, position: int) -> "Listing | None":
        m = re.search(r"product-item-id-(\d+)", t.get("box") or "") or re.search(r"/items/(\d+)", t.get("href") or "")
        if not m:
            return None
        label = t.get("label") or ""
        # label: "<title>, Brand: Levi's, Condition: Very good, Size: W32, 26.00 £, 28.00 £"
        head = re.match(r"^(.*?), [^,:]{2,20}: ", label)
        title = head.group(1) if head else label.split(", ")[0]
        tail = re.search(r",\s*([\d.]+)\s*\S+,\s*([\d.]+)\s*\S+\s*$", label)
        price, cur = money(t.get("price"))
        total, _ = money(t.get("total"))
        if tail:  # the label always uses a dot decimal, so prefer it
            price, total = float(tail.group(1)), float(tail.group(2))
        parts = [p.strip() for p in (t.get("subtitle") or "").split("·") if p.strip()]
        size, condition = (parts[0], parts[-1]) if len(parts) >= 2 else (None, parts[0] if parts else None)
        href = (t.get("href") or "").split("?")[0]
        return cls(
            id=int(m.group(1)),
            title=title,
            brand=t.get("brand") or None,
            size=size,
            condition=condition,
            price=price,
            total_price=total,
            currency=cur,
            favourites=int(t["favourites"]) if (t.get("favourites") or "").isdigit() else 0,
            url=base + href,
            image=t.get("image") or None,
            page=page,
            position=position,
        )


@dataclass
class Item:
    """One /items/<id> page."""

    id: int
    found: bool = True
    title: str | None = None
    brand: str | None = None
    size: str | None = None
    condition: str | None = None
    material: str | None = None
    colour: str | None = None
    uploaded: str | None = None
    category: str | None = None
    breadcrumbs: list[str] = field(default_factory=list)
    price: float | None = None  # as displayed on the page
    total_price: float | None = None
    currency: str | None = None
    listed_price: float | None = None  # JSON-LD offer, in the seller's currency
    listed_currency: str | None = None
    availability: str | None = None
    schema_condition: str | None = None
    shipping_from: float | None = None
    can_buy: bool = False
    seller: str | None = None
    seller_rating: float | None = None
    seller_reviews: int | None = None
    seller_last_seen: str | None = None
    photos: list[str] = field(default_factory=list)
    description: str | None = None
    url: str | None = None

    @classmethod
    def from_rules(cls, item_id: int, r: dict, url: str) -> "Item":
        ld: dict = {}
        raw = re.sub(r"^<script[^>]*>|</script>$", "", (r.get("ld") or "").strip())
        if raw:
            try:
                ld = json.loads(raw)
            except json.JSONDecodeError:
                ld = {}
        if ld.get("@type") != "Product":  # only trust JSON-LD that describes the listing
            ld = {}
        offer = ld.get("offers") or {}
        attrs = {(a.get("key") or "").replace("item-attributes-", ""): a.get("value") for a in r.get("attributes") or []}
        price, cur = money(r.get("price"))
        total, _ = money(r.get("total"))
        ship, _ = money(r.get("shipping"))
        rating = re.search(r"([\d.]+) out of", r.get("rating") or "")
        reviews = (r.get("reviews") or "").strip()
        return cls(
            id=item_id,
            title=r.get("title") or ld.get("name"),
            brand=(ld.get("brand") or {}).get("name"),
            size=attrs.get("size"),
            condition=attrs.get("status"),
            material=attrs.get("material"),
            colour=attrs.get("color") or ld.get("color"),
            uploaded=attrs.get("upload_date"),
            category=ld.get("category"),
            breadcrumbs=r.get("breadcrumbs") or [],
            price=price,
            total_price=total,
            currency=cur,
            listed_price=float(offer["price"]) if offer.get("price") is not None else None,
            listed_currency=offer.get("priceCurrency"),
            availability=offer.get("availability"),
            schema_condition=offer.get("itemCondition"),
            shipping_from=ship,
            can_buy=bool(r.get("buy_button")),
            seller=r.get("seller") or None,
            seller_rating=float(rating.group(1)) if rating else None,
            seller_reviews=int(reviews) if reviews.isdigit() else None,
            seller_last_seen=r.get("last_seen") or None,
            photos=list(dict.fromkeys(r.get("photos") or [])),  # the gallery renders twice
            description=r.get("description") or ld.get("description"),
            url=url,
        )


class VintedClient:
    def __init__(self, api_key: str, domain: str = DEFAULT_DOMAIN, timeout: int = 90):
        self.api_key = api_key
        self.base = "https://" + domain
        self.timeout = timeout
        self.session = requests.Session()
        self.credits = 0

    def _get(self, url: str, rules: dict, retries: int = 4) -> tuple[int, dict, str]:
        """One ScrapingBee call. Returns (status, extracted JSON, resolved URL).

        ScrapingBee does not bill its own HTTP 500, so those are retried.
        Vinted's 404 and 410 are passed through (and billed), and returned as is.
        """
        params = {"url": url, "render_js": "false", "extract_rules": json.dumps(rules)}
        for attempt in range(retries):
            r = self.session.get(
                API,
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            self.credits += int(r.headers.get("spb-cost") or 0)
            if r.status_code == 500 and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (404, 410):
                return r.status_code, {}, r.headers.get("spb-resolved-url", url)
            r.raise_for_status()
            return r.status_code, r.json(), r.headers.get("spb-resolved-url", url)
        raise RuntimeError("unreachable")

    def catalog_url(self, query: str, page: int = 1, order: str | None = None,
                    price_from: float | None = None, price_to: float | None = None,
                    currency: str | None = None, extra: list[tuple[str, str]] | None = None) -> str:
        q: list[tuple[str, str]] = [("search_text", query)]
        if order:
            q.append(("order", order))
        if price_from is not None:
            q.append(("price_from", f"{price_from:g}"))
        if price_to is not None:
            q.append(("price_to", f"{price_to:g}"))
        if (price_from is not None or price_to is not None) and currency:
            q.append(("currency", currency))
        q += extra or []
        if page > 1:
            q.append(("page", str(page)))
        return f"{self.base}/catalog?{urlencode(q)}"

    def search_page(self, query: str, page: int = 1, **kw) -> tuple[list[Listing], bool]:
        """One catalog page. Returns (listings, has_next)."""
        url = self.catalog_url(query, page, **kw)
        for attempt in range(3):
            _, d, _ = self._get(url, CATALOG_RULES)
            tiles = d.get("items") or []
            if tiles or "Vinted" in (d.get("page_title") or ""):
                break  # a real catalog page, even if the search matched nothing
            time.sleep(3)  # a billed page without the catalog shell: try again
        else:
            raise RuntimeError(f"no catalog markup in the response for {url}")
        rows = [Listing.from_tile(t, self.base, page, i + 1) for i, t in enumerate(tiles)]
        has_next = bool(d.get("next")) and d.get("next_disabled") != "true"
        return [x for x in rows if x], has_next

    def search(self, query: str, pages: int = 1, verbose: bool = True, **kw) -> Iterator[Listing]:
        """Walk the catalog pagination the way a visitor clicks Next."""
        seen: set[int] = set()
        for page in range(1, min(pages, MAX_PAGES) + 1):
            rows, has_next = self.search_page(query, page, **kw)
            fresh = [x for x in rows if x.id not in seen]
            seen.update(x.id for x in fresh)
            if verbose:
                note = "" if len(rows) == PER_PAGE or not has_next else "  (short page)"
                dup = f", {len(rows) - len(fresh)} repeated from earlier pages" if len(fresh) < len(rows) else ""
                print(f"  page {page}: {len(rows)} tiles{dup}{note}", file=sys.stderr)
            yield from fresh
            if not has_next:
                break

    def item(self, ref: str | int) -> Item:
        m = re.search(r"(\d{6,})", str(ref))
        if not m:
            raise ValueError(f"not an item id or URL: {ref}")
        item_id = int(m.group(1))
        status, d, resolved = self._get(f"{self.base}/items/{item_id}", ITEM_RULES)
        if status in (404, 410) or not (d.get("ld") or d.get("price")):
            return Item(id=item_id, found=False, url=resolved)
        return Item.from_rules(item_id, d, resolved)


def write_csv(path: str, rows: list) -> None:
    if not rows:
        return
    names = [f.name for f in fields(rows[0])]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=names)
        w.writeheader()
        for r in rows:
            d = asdict(r)
            w.writerow({k: "|".join(v) if isinstance(v, list) else v for k, v in d.items()})


def write_json(path: str, rows: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([asdict(r) for r in rows], fh, ensure_ascii=False, indent=1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Vinted catalog and item pages via ScrapingBee")
    ap.add_argument("--domain", default=DEFAULT_DOMAIN, help="www.vinted.co.uk (default), www.vinted.fr, ...")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="catalog search results")
    s.add_argument("query")
    s.add_argument("--pages", type=int, default=1, help=f"1 to {MAX_PAGES}, 1 credit each")
    s.add_argument("--order", choices=["relevance", "newest_first", "price_low_to_high", "price_high_to_low"])
    s.add_argument("--price-from", type=float)
    s.add_argument("--price-to", type=float)
    s.add_argument("--currency", default="GBP", help="sent with a price filter")
    s.add_argument("--filter", action="append", default=[], metavar="KEY=VALUE",
                   help="any catalog URL parameter, e.g. 'brand_ids[]=10' or 'status_ids[]=6'")
    s.add_argument("--csv")
    s.add_argument("--json")

    i = sub.add_parser("item", help="one or more item pages")
    i.add_argument("refs", nargs="+", help="item ids or /items/ URLs")
    i.add_argument("--csv")
    i.add_argument("--json")

    a = ap.parse_args()
    key = os.environ.get("SCRAPINGBEE_API_KEY")
    if not key:
        sys.exit("set SCRAPINGBEE_API_KEY")
    client = VintedClient(key, a.domain)

    if a.cmd == "search":
        extra = [tuple(f.split("=", 1)) for f in a.filter]
        rows = list(client.search(a.query, a.pages, order=a.order, price_from=a.price_from,
                                  price_to=a.price_to, currency=a.currency, extra=extra))
        for r in rows[:5]:
            print(f"{r.id}  {r.title[:34]:34}  {(r.brand or '')[:12]:12}  {(r.size or '-')[:12]:12}  "
                  f"{(r.condition or '')[:16]:16}  {r.price:>7.2f} {r.currency}  total {r.total_price:.2f}")
        print(f"{len(rows)} listings, {client.credits} credits")
    else:
        rows = []
        for ref in a.refs:
            it = client.item(ref)
            rows.append(it)
            if it.found:
                print(json.dumps({k: v for k, v in asdict(it).items() if k not in ("photos", "description")},
                                 ensure_ascii=False))
            else:
                print(json.dumps({"id": it.id, "found": False}))
        print(f"{sum(r.found for r in rows)} of {len(rows)} items found, {client.credits} credits")

    if a.csv:
        write_csv(a.csv, rows)
    if a.json:
        write_json(a.json, rows)


if __name__ == "__main__":
    main()
