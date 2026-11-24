// Look up Vinted item pages through ScrapingBee and print one JSON line each.
// Node 18+ (global fetch), no dependencies.
//
//   SCRAPINGBEE_API_KEY=... node vinted_items.js 10952746328 https://www.vinted.co.uk/items/10951409620
//   VINTED_DOMAIN=www.vinted.fr node vinted_items.js <id>

const API = "https://app.scrapingbee.com/api/v1/";
const DOMAIN = process.env.VINTED_DOMAIN || "www.vinted.co.uk";

// The same selectors as examples/vinted_client.py, trimmed to what a price
// check needs: JSON-LD for the offer, the details list, seller rating.
// The JSON-LD offer is in the seller's currency, which is not always the
// site's: a cross-border listing on vinted.co.uk carried "AUD" there while
// the page showed pounds. So price and total come from the visible markup.
const RULES = {
  ld: { selector: "script[type='application/ld+json']", output: "html" },
  price: "div[data-testid='item-price']",
  total: "div[data-testid='item-sidebar-price-container'] span[data-testid='total-combined-price']",
  size: "div[data-testid='item-attributes-size'] div[itemprop]",
  condition: "div[data-testid='item-attributes-status'] div[itemprop]",
  uploaded: "div[data-testid='item-attributes-upload_date'] div[itemprop]",
  shipping: "span[data-testid='item-shipping-banner-price']",
  seller: "span[data-testid='profile-username']",
  rating: { selector: "div[role='group'][aria-label^='Member rated']", output: "@aria-label" },
  reviews: "div.web_ui__Rating__label",
};

const SYMBOLS = { "£": "GBP", "€": "EUR", $: "USD" };

function currency(text) {
  const m = (text || "").match(/[£€$]/);
  return m ? SYMBOLS[m[0]] : null;
}

function amount(text) {
  const m = (text || "").match(/\d[\d.,]*/);
  if (!m) return null;
  let n = m[0];
  n = /,\d{2}$/.test(n) ? n.replace(/\./g, "").replace(",", ".") : n.replace(/,/g, "");
  return Number(n);
}

async function scrape(url, attempts = 4) {
  const qs = new URLSearchParams({ url, render_js: "false", extract_rules: JSON.stringify(RULES) });
  for (let i = 0; i < attempts; i++) {
    const res = await fetch(`${API}?${qs}`, {
      headers: { Authorization: `Bearer ${process.env.SCRAPINGBEE_API_KEY}` },
    });
    const cost = Number(res.headers.get("spb-cost") || 0);
    if (res.status === 500 && i < attempts - 1) {
      // ScrapingBee does not bill its own 500s
      await new Promise((r) => setTimeout(r, 2000 * (i + 1)));
      continue;
    }
    if (res.status === 404 || res.status === 410) return { status: res.status, cost, data: null };
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
    return { status: res.status, cost, data: await res.json(), resolved: res.headers.get("spb-resolved-url") };
  }
}

async function main() {
  if (!process.env.SCRAPINGBEE_API_KEY) throw new Error("set SCRAPINGBEE_API_KEY");
  const refs = process.argv.slice(2);
  if (!refs.length) throw new Error("pass one or more item ids or /items/ URLs");
  let credits = 0;
  for (const ref of refs) {
    const id = (String(ref).match(/(\d{6,})/) || [])[1];
    if (!id) {
      console.error(`skipping ${ref}`);
      continue;
    }
    const { cost, data, resolved } = await scrape(`https://${DOMAIN}/items/${id}`);
    credits += cost;
    if (!data || !data.ld) {
      console.log(JSON.stringify({ id: Number(id), found: false }));
      continue;
    }
    const ld = JSON.parse(data.ld.replace(/^<script[^>]*>/, "").replace(/<\/script>$/, ""));
    const offer = ld.offers || {};
    const rating = (data.rating.match(/([\d.]+) out of/) || [])[1];
    console.log(
      JSON.stringify({
        id: Number(id),
        title: ld.name,
        brand: (ld.brand || {}).name || null,
        category: ld.category || null,
        size: data.size || null,
        condition: data.condition || null,
        price: amount(data.price), // what the page shows, in the site currency
        total: amount(data.total),
        currency: currency(data.price),
        listed: offer.price != null ? `${offer.price} ${offer.priceCurrency}` : null, // JSON-LD, seller currency
        availability: offer.availability || null,
        shipping_from: amount(data.shipping),
        uploaded: data.uploaded || null,
        seller: data.seller || null,
        seller_rating: rating ? Number(rating) : null,
        seller_reviews: /^\d+$/.test(data.reviews) ? Number(data.reviews) : null,
        url: resolved,
      })
    );
  }
  console.error(`${refs.length} lookups, ${credits} credits`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
