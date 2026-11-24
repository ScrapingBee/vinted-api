# Vinted API

<p align="center">
  <a href="https://www.scrapingbee.com/">
    <img src="REPLACE_WITH_SCREENSHOT_URL" alt="vinted-api" />
  </a>
</p>

[![checks](https://github.com/ScrapingBee/vinted-api/workflows/checks/badge.svg)](https://github.com/ScrapingBee/vinted-api/actions)
[![license](https://img.shields.io/github/license/ScrapingBee/vinted-api.svg)](LICENSE)

This repo is a price research kit for one question: what do second hand items list for on Vinted UK, by condition and by size? It is a small [Vinted API](https://www.scrapingbee.com/scrapers/vinted-api/) client in Python and Node that reads the public catalog grid and public item pages of vinted.co.uk through [ScrapingBee](https://www.scrapingbee.com/), turns them into typed rows, and works out price quartiles by condition and size. Each page costs 1 credit.

The README is written as a research log. Each entry is something we measured on 2026-11-24, with the request that produced it.

```bash
pip install requests
export SCRAPINGBEE_API_KEY=your_key
python examples/vinted_price_bands.py "levis 501 selvedge" --bands 0 20 50 500 --csv selvedge.csv
```

```
band      0-20 GBP:   27 new,   0 repeats,  1 pages, complete
band     20-50 GBP:  149 new,   0 repeats,  2 pages, complete
band    50-500 GBP:  241 new,   0 repeats,  3 pages, complete

417 unique listings, 0 repeats dropped, 0 outside their band, 6 credits

'levis 501 selvedge' on www.vinted.co.uk: 417 listings, asking price p25 34.91, median 55.00, p75 85.00 GBP
```

| File | Job | Credits |
|---|---|---|
| [`examples/vinted_client.py`](examples/vinted_client.py) | `VintedClient`, `Listing` and `Item` dataclasses, `search` and `item` subcommands, CSV/JSON export | 1 per page |
| [`examples/vinted_price_bands.py`](examples/vinted_price_bands.py) | splits a search into price bands, dedupes, prints quartiles by condition and size | 1 per page |
| [`examples/vinted_items.js`](examples/vinted_items.js) | Node 18 item lookup, one JSON line per listing | 1 per item |

## Entry 1: what Vinted's robots.txt allows

Fetched through ScrapingBee with `render_js=false` for 1 credit. The lines that shape this repo:

```
User-agent: *
Disallow: /checkout
Disallow: /util
Disallow: /apipie/
Disallow: /member/
Disallow: /inbox
Allow: /
Content-Signal: ai-train=no, search=yes, ai-input=yes
```

So `/catalog` and `/items/` are open, and `/member/` (seller profiles) is closed apart from ten allow-listed accounts. Nothing here requests a `/member/` URL, not even the profile link that sits on every item page. The seller name, star rating and review count in this repo all come off the item page itself.

The file opens with a comment block that matters as much as the rules. It forbids automated agents from creating accounts, adding to carts or checking out, and it sets `ai-train=no`, saying content may not be used for model training, fine tuning or dataset creation by AI systems. That rules out two kinds of project. This code does no buying, offering, favouriting or messaging, and the output is meant for price research, not for feeding a model. vinted.fr serves the same rules.

## Entry 2: the cheapest request that returns real listings

The catalog is a Next.js page that renders on the server, so the full grid is in the first HTML response. We started at 1 credit and checked for listings, not for a 200:

| Request | Credits | Time | What came back |
|---|---|---|---|
| `/catalog?search_text=levis+501`, `render_js=false` | 1 | about 3 s | 96 grid tiles, pagination, full RSC payload |
| same, `render_js=true` | 5 | not timed | the same 96 tiles |
| `/items/10951409620`, `render_js=false` | 1 | 1.5 s | JSON-LD, details list, seller rating |
| same, `render_js=true` | 5 | 8.9 s | the same fields |
| `/items/99999999999` (no such item) | 1 | | HTTP 404, passed through and billed |

Classic proxies with no JavaScript were enough for every page in this log, about 140 requests in all, and none came back as a challenge page. The client still checks the page `<title>` and retries a response that has no catalog markup, because a billed empty page is the failure you would not otherwise notice. One malformed selector got an HTTP 500 back from ScrapingBee with `spb-cost: 0`; those are retried and not billed.

No `country_code` was set (classic proxies do not geotarget). vinted.co.uk still priced everything in pounds and vinted.fr in euros, so in our tests the currency followed the domain.

## Entry 3: what one catalog tile holds

Each listing in the grid is a `div[data-testid="grid-item"]` with testids built from the item id. Trimmed from the 1 credit HTML (SVG icons and wrapper divs removed):

```html
<div data-testid="grid-item" class="HmDNda_feed-grid__item">
  <div class="NoC3Da_new-item-box__container" data-testid="product-item-id-10951409620">
    <img src="https://images1.vinted.net/t/05_0125e_NmEZGjX4zh859t97MGotmVsP/310x430/f72bba74.webp?s=d697b3cddbb6626e9aa1c226605c211a077ba74d"
         alt="Levis dark wash 501 jeans, Brand: Levi&#x27;s, Condition: Very good, Size: XS / UK 4-6, 10.00 £, 11.20 £"
         data-testid="product-item-id-10951409620--image--img"/>
    <a href="/items/10951409620-levis-dark-wash-501-jeans?referrer=catalog"
       data-testid="product-item-id-10951409620--overlay-link"
       title="Levis dark wash 501 jeans, Brand: Levi&#x27;s, Condition: Very good, Size: XS / UK 4-6, 10.00 £, 11.20 £">
    <button aria-label="Add to favourites, favourited by 5 users" data-testid="product-item-id-10951409620--favourite">
      <span data-testid="favourite-count-text">5</span></button>
    <p data-testid="product-item-id-10951409620--description-title">Levi&#x27;s</p>
    <p data-testid="product-item-id-10951409620--description-subtitle">XS / UK 4-6 · Very good</p>
    <span data-testid="product-item-id-10951409620--price-text">£10.00</span>
    <button aria-label="£11.20 includes Vinted fee">
      <span data-testid="total-combined-price">£11.20</span>
      <span data-testid="service-fee-included-title">incl. Vinted fee</span></button>
```

The `title` on the overlay link is the most useful string on the tile. It carries title, brand, condition, size, price and total in one place, and its numbers always use a dot decimal, even on vinted.fr where the visible price reads `20,00 €`. The parser takes the two prices from the end of that string and falls back to the visible text.

The same data also sits in the React Server Components payload (`self.__next_f.push(...)` script tags), as typed JSON with currency codes:

```json
{"id": 10951409620,
 "productItem": {"id": 10951409620, "title": "Levis dark wash 501 jeans",
   "url": "/items/10951409620-levis-dark-wash-501-jeans", "favouriteCount": 5,
   "price": {"amount": "10.00", "currencyCode": "GBP"},
   "serviceFee": {"amount": "1.20", "currencyCode": "GBP"},
   "totalItemPrice": {"amount": "11.20", "currencyCode": "GBP"},
   "isPromoted": false,
   "user": {"id": 73953745, "photo": null, "thumbnailUrl": null, "isBusiness": false},
   "itemBox": {"firstLine": "Levi's", "secondLine": "XS / UK 4-6 · Very good"}}}
...
"pagination": {"current_page": 1, "per_page": 96, "total_entries": 960, "total_pages": 10}
```

We used it to check the DOM numbers, but the client reads the DOM. The payload is split across about 60 script tags and full of `"$undefined"` references, the page weighs 3.7 MB, and `extract_rules` can return just the tiles as JSON. These are the rules the client sends:

```python
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
```

Quote the attribute values. Our first try used `[data-testid$=--price-text]` without quotes, and the selector parser rejected it (`Expected string or ident, got <DELIM`), which ScrapingBee returned as an unbilled 500.

## Entry 4: a Vinted scraper stops at 960 results

The URL parameters the catalog UI writes are plain query strings, and the RSC payload echoes back how each one was read:

```
/catalog?search_text=levis 501&price_from=20&price_to=40&currency=GBP&brand_ids[]=10&status_ids[]=6&order=newest_first

"filters": {"priceFrom": "20", "priceTo": "40", "currency": "GBP", "sortBy": "newest_first", "query": "levis 501",
            "page": 1, "perPage": 96,
            "selectedDynamicFilters": [{"type": "brand", "ids": ["10"]}, {"type": "status", "ids": ["6"]}]}
```

`brand_ids[]=10` is Levi's and `status_ids[]=6` is "New with tags", both read back from that payload. The `order` values seen in the page are `relevance`, `newest_first`, `price_low_to_high` and `price_high_to_low`.

Pagination goes through `a[data-testid="catalog-pagination--page-N"]` links and a Next link. For `search_text=nike`, page 10 had 96 tiles, a Next link with `aria-disabled="true"`, and a payload reading `"total_entries": 960, "total_pages": 10`. Page 11 returned zero tiles. The same 960 showed up on all three large searches we checked, with and without filters, so it is a ceiling and not a count. A search that matches 20,000 listings and one that matches 960 look the same from the outside.

`vinted_price_bands.py` deals with that by splitting the query into price bands, each with its own 960 ceiling, and flagging any band that fills all ten pages:

```bash
python examples/vinted_price_bands.py "levis 501" --bands 0 15 25 40 400 \
    --filter "brand_ids[]=10" --filter "status_ids[]=6" --csv nwt.csv
```

```
band      0-15 GBP:  960 new,   0 repeats, 10 pages, hit the 10 page ceiling, split this band
band     15-25 GBP:  960 new,   0 repeats, 10 pages, hit the 10 page ceiling, split this band
band     25-40 GBP:  960 new,   0 repeats, 10 pages, hit the 10 page ceiling, split this band
band    40-400 GBP:  960 new,   0 repeats, 10 pages, hit the 10 page ceiling, split this band

3840 unique listings, 0 repeats dropped, 0 outside their band, 40 credits
```

Search text on Vinted is loose. "levis 501" filtered to the Levi's brand still returns T-shirts and shorts, and even new-with-tags stock fills every band, so this query needs much narrower bands to reach the bottom. The selvedge run at the top of this README is what a finished sweep looks like.

Two things went wrong in the first version, and the fixes are in the script:

- **Bands overlapped.** Both `price_from` and `price_to` are inclusive. A six band run over all Levi's 501 listings dropped 382 repeats, and 782 of the kept listings sat exactly on a band edge (251 at £8.00 alone). Every band but the last now stops a penny short, at `price_to=11.99` for an 8 to 12 band, and the next run had zero repeats.
- **Page 10 looked like a finished band.** Its Next link is disabled even when more listings match. The script now treats a full page 10 as the ceiling.

The price filter applies to the item price, not the total with fees: across 9,218 tiles from the two big runs, none fell outside its band.

## Entry 5: one item page

`/items/<id>` redirects (HTTP 307) to the slugged URL, and `spb-resolved-url` gives the final one. The page carries a single JSON-LD block, which we checked describes the listing and not the site:

```json
{"@type": "Product", "name": "Levis dark wash 501 jeans",
 "description": "Slim fit straight leg jeans in dark wash. Levis 501s. Lovely cut and quality. ...",
 "image": "https://images1.vinted.net/t/05_0125e_NmEZGjX4zh859t97MGotmVsP/f800/f72bba74.webp?s=7cd885d9e42868b63c0196fe28bd32cab0858213",
 "brand": {"@type": "Brand", "name": "Levi's", "sameAs": "https://www.wikidata.org/wiki/Q127962"},
 "offers": {"@type": "Offer", "url": "https://www.vinted.co.uk/items/10951409620-levis-dark-wash-501-jeans",
            "priceCurrency": "GBP", "price": 10, "availability": "InStock", "itemCondition": "UsedCondition"},
 "category": "Women Straight jeans", "color": "Blue", "@context": "https://schema.org"}
```

The details list holds what JSON-LD leaves out. Each row is a `div[data-testid="item-attributes-<code>"]` with an `itemProp` value cell:

```html
<div class="details-list__item u-flexbox u-position-relative" data-testid="item-attributes-status">
  <div class="details-list__item-value"><span class="web_ui__Text__text ...">Condition</span></div>
  <div class="details-list__item-value" itemProp="status"><span class="... web_ui__Text__bold">Very good</span></div>
</div>
```

The rows we saw were `size`, `status`, `material`, `color` and `upload_date`. Brand sits in its own row next to a menu button, so the client takes it from JSON-LD. The seller block is a username, a star rating in an `aria-label`, and a review count:

```html
<span data-testid="profile-username">chazpazz</span>
<div class="web_ui__Rating__rating web_ui__Rating__small" role="group" aria-label="Member rated 4.9 out of 5">
  ...<div class="web_ui__Rating__label"><span>118</span></div>
<span data-testid="seller-last-logged-in">Last seen 2 hours ago</span>
```

Rules for the item page, with the JSON-LD script read as `"output": "html"` and the tags stripped in Python:

```python
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
    "shipping": "span[data-testid='item-shipping-banner-price']",
    "seller": "span[data-testid='profile-username']",
    "rating": {"selector": "div[role='group'][aria-label^='Member rated']", "output": "@aria-label"},
    "reviews": "div.web_ui__Rating__label",
    # description, last_seen, breadcrumbs, photos, buy_button: see the file
}
```

`total-combined-price` also appears on every tile in the "similar items" feed lower down the page, so the rule scopes it to the sidebar price container. The gallery renders twice (desktop and mobile), and the client dedupes the photo URLs.

```bash
python examples/vinted_client.py item 10936219942 10951409620 99999999999 --json items.json
```

```
{"id": 10936219942, "found": true, "title": "Levi’s 501 Jeans", "brand": "Levi's", "size": "XS / UK 4-6",
 "condition": "Very good", "material": "Denim", "colour": "Navy", "uploaded": "a day ago",
 "category": "Women Straight jeans", "price": 15.43, "total_price": 16.9, "currency": "GBP",
 "listed_price": 30.0, "listed_currency": "AUD", "availability": "InStock", "schema_condition": "UsedCondition",
 "shipping_from": 8.61, "can_buy": true, "seller": "jesscobban1", "seller_rating": null, "seller_reviews": 0, ...}
{"id": 10951409620, "found": true, "title": "Levis dark wash 501 jeans", ..., "price": 10.0, "total_price": 11.2,
 "currency": "GBP", "listed_price": 10.0, "listed_currency": "GBP", "shipping_from": 0.0,
 "seller": "chazpazz", "seller_rating": 4.9, "seller_reviews": 118, "seller_last_seen": "Last seen 2 hours ago", ...}
{"id": 99999999999, "found": false}
2 of 3 items found, 3 credits
```

The first item is why `Item` has two prices. Its JSON-LD offer says `30 AUD` while the page shows £15.43, so JSON-LD carries the seller's own currency and the page shows a converted one. Our first version read the price from JSON-LD and reported "30 AUD" next to a £16.90 total. The client now takes `price` and `currency` from the visible markup and keeps the JSON-LD pair as `listed_price` and `listed_currency`.

Shipping reads "from £0.00" on the UK listings we opened and "from £8.61" on that cross-border one. It is the lowest option the banner advertises, not a quote for any address.

Upload time is relative ("2 hours ago", "a day ago"), so record when you scraped if you need dates. A sold listing was not among the items we opened, so how the page marks one is untested; `can_buy` reports whether the Buy now button was present.

## Entry 6: the buyer fee, measured

Every tile shows the item price and a "total incl. Vinted fee". Over 5,378 unique tiles from one Levi's run, 5,348 had a fee of exactly £0.70 plus 5% of the price (£10.00 becomes £11.20, £26.00 becomes £28.00). The other 30 fit £0.30 plus 8% (£2.00 becomes £2.46, £65.94 becomes £71.52). The tile does not say which schedule applies or why, so the client stores both numbers and leaves the fee to subtraction.

## Entry 7: what Levi's 501s list for on Vinted UK

From the six band, all Levi's run above (5,378 listings after dedupe, 61 credits, every band capped, so read it as a large sample and not a census):

```
'levis 501' on www.vinted.co.uk: 5378 listings, asking price p25 10.00, median 17.84, p75 30.00 GBP

By condition
                             n      p25   median      p75  median total
  Very good               2965    10.09    15.52    27.15         17.00
  Good                     941     8.00    11.64    20.00         12.92
  New with tags            767    20.00    30.00    45.00         32.20
  New without tags         486    13.96    25.00    40.00         26.95
  Satisfactory             219     5.00     7.00    10.86          8.05
```

And for "levis 501 selvedge", which fit inside the ceiling (417 listings, 6 credits):

```
By condition
                             n      p25   median      p75  median total
  Very good                204    31.03    50.00    70.00         53.20
  New with tags             83    50.22    70.00    90.00         74.20
  Good                      74    29.62    50.22   110.00         53.42
  New without tags          41    30.00    50.00    84.95         53.20
  Satisfactory              15    35.02    80.00   275.00         84.70

Most listed sizes
  W32                       63    40.89    69.82   100.00         74.01
  S / UK 8-10               45    30.00    39.00    55.00         41.65
  W30                       41    45.00    60.00    90.00         63.70
```

These are asking prices of listings that were live on 2026-11-24, not sale prices. Sold listings drop out of the catalog, so nothing in this repo can tell you what an item went for.

## Vinted API in Python: the client

`VintedClient` wraps two calls and a parser for each page type:

```python
import os
from vinted_client import VintedClient

client = VintedClient(os.environ["SCRAPINGBEE_API_KEY"], domain="www.vinted.co.uk")
for row in client.search("levis 501", pages=3, order="price_low_to_high",
                         price_from=20, price_to=40, extra=[("status_ids[]", "6")]):
    print(row.id, row.brand, row.size, row.condition, row.price, row.total_price, row.currency)

item = client.item("https://www.vinted.co.uk/items/10951409620-levis-dark-wash-501-jeans")
print(item.seller, item.seller_rating, item.seller_reviews, item.shipping_from)
print(client.credits)  # summed from spb-cost
```

- **Retries.** `_get()` retries ScrapingBee's HTTP 500 up to four times with a growing pause, since those are not billed. A 404 or 410 from Vinted comes back as `Item(found=False)` and is billed at 1 credit.
- **Empty pages.** `search_page()` retries a response whose title does not mention Vinted and that has no tiles.
- **Pagination.** `search()` walks pages 1 to 10, stops on a disabled Next link, drops ids already seen on earlier pages, and prints a warning on a short page that still has a Next link.
- **Typed rows.** `Listing` has 13 fields and `Item` has 27, both dataclasses, written out by `write_csv()` (list fields joined with `|`) and `write_json()`.

```bash
python examples/vinted_client.py search "levis 501" --order price_low_to_high \
    --price-from 20 --price-to 40 --filter "status_ids[]=6" --json new.json
```

```
  page 1: 96 tiles
10950928275  Levi’s 501 Original Straight Jeans  Levi's        Other         New with tags       20.00 GBP  total 21.70
10944369945  Levi’s 501 grey high rise shorts S  Levi's        M / UK 12-14  New with tags       20.00 GBP  total 21.70
10929991905  Levi Light Wash Demin 501 Shorts    Levi's        M / UK 12-14  New with tags       20.00 GBP  total 21.70
96 listings, 1 credits
```

`--domain www.vinted.fr` points the client at the French site. The same catalog rules returned 96 tiles from one French search page, with labels such as `Marque: Levi's, État: Très bon état` and prices in euros. Item pages and the price bands script were only run against vinted.co.uk.

## Node.js

```bash
SCRAPINGBEE_API_KEY=... node examples/vinted_items.js 10936219942 https://www.vinted.co.uk/items/10951409620 123456789012
```

```
{"id":10936219942,"title":"Levi’s 501 Jeans","brand":"Levi's","category":"Women Straight jeans","size":"XS / UK 4-6","condition":"Very good","price":15.43,"total":16.9,"currency":"GBP","listed":"30 AUD","availability":"InStock","shipping_from":8.61,"uploaded":"a day ago","seller":"jesscobban1","seller_rating":null,"seller_reviews":0,"url":"https://www.vinted.co.uk/items/10936219942-levis-501-jeans"}
{"id":10951409620,"title":"Levis dark wash 501 jeans","brand":"Levi's","category":"Women Straight jeans","size":"XS / UK 4-6","condition":"Very good","price":10,"total":11.2,"currency":"GBP","listed":"10 GBP","availability":"InStock","shipping_from":0,"uploaded":"2 hours ago","seller":"chazpazz","seller_rating":4.9,"seller_reviews":118,"url":"https://www.vinted.co.uk/items/10951409620-levis-dark-wash-501-jeans"}
{"id":123456789012,"found":false}
3 lookups, 3 credits
```

It uses the global `fetch` of Node 18, has no dependencies, and runs inside `async function main()`. Set `VINTED_DOMAIN` to point it at another Vinted site.

## Is there an official Vinted API?

We did not find a public, documented API for reading Vinted listings, and this repo does not use one. robots.txt disallows `/apipie/`, and nothing here calls Vinted's own backend; the data comes from the HTML a logged out browser receives. If Vinted changes a `data-testid`, the fix goes in `CATALOG_RULES` or `ITEM_RULES`. For the ScrapingBee side, the [API documentation](https://www.scrapingbee.com/documentation/) lists every parameter used here, the [data extraction guide](https://www.scrapingbee.com/documentation/data-extraction/) covers the `extract_rules` syntax, and [ScrapingBee pricing](https://www.scrapingbee.com/pricing/) lists the plans. New accounts start with 1,000 free credits, enough for 1,000 catalog pages at this site's 1 credit cost.

| Job | Calls | Credits |
|---|---|---|
| 96 listings from one search page | 1 | 1 |
| A full search, 960 listings | 10 | 10 |
| One item page with seller rating | 1 | 1 |
| An item id that does not exist (HTTP 404) | 1 | 1 |
| The six band Levi's 501 sweep in Entry 7 | 61 | 61 |

## Scope

- Logged out pages only. ScrapingBee's terms do not allow scraping behind a login, and nothing here signs in or sends a member cookie. Favourites, offers, messages and purchase history are account features and are not read.
- No `/member/` pages, per robots.txt. Seller data is limited to what an item page prints.
- Seller usernames are personal data under UK GDPR. `vinted_price_bands.py` never collects them; if you store `Item.seller`, have a reason to.
- No buying, offering or messaging automation of any kind, in line with Vinted's robots.txt notice.

Related ScrapingBee pages for resale marketplaces: [Depop scraper API](https://www.scrapingbee.com/scrapers/depop-scraper-api/), [Poshmark API](https://www.scrapingbee.com/scrapers/poshmark-api/), [Grailed API](https://www.scrapingbee.com/scrapers/grailed-api/), [Mercari API](https://www.scrapingbee.com/scrapers/mercari-api/), [Wallapop API](https://www.scrapingbee.com/scrapers/wallapop-api/), [Leboncoin API](https://www.scrapingbee.com/scrapers/leboncoin-api/), [eBay scraper](https://www.scrapingbee.com/scrapers/ebay-scraper/).

## FAQ

**How do I use the Vinted API in Python?**
Install `requests`, set `SCRAPINGBEE_API_KEY`, and run `python examples/vinted_client.py search "<query>" --pages 2 --csv out.csv`. For item level fields such as material, shipping and seller rating, run the `item` subcommand with ids or URLs. Both use `render_js=false` and cost 1 credit a page.

**Why does my Vinted scraper stop at 960 results?**
The public catalog shows 10 pages of 96, and the page payload reported `total_entries: 960` for every large search we tried. Split the search with `price_from` and `price_to`, which is what `vinted_price_bands.py` does, and narrow any band that still fills all ten pages.

**Does scraping Vinted need JavaScript rendering?**
Not for the catalog or item pages on vinted.co.uk in our tests. The server returns the full grid and the full item page, and rendering only raised the cost from 1 to 5 credits with the same fields.

**Can I get Vinted seller ratings without opening profile pages?**
Yes. Every item page prints the seller's username, a "Member rated 4.9 out of 5" label and a review count, and those are the only seller fields this repo collects. Profile pages under `/member/` are disallowed by robots.txt.

**Can I see what Vinted items sold for?**
Not from logged out pages. Sold listings leave the catalog, so the prices in this repo are asking prices of live listings.

## License

MIT. See [LICENSE](LICENSE).
