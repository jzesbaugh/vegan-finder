#!/usr/bin/env python3
"""
Weekly Kroger plant-based sale check.

Authenticates to the Kroger public API with the client_credentials grant,
resolves a store from a ZIP code, searches a curated set of plant-based
terms, and reports items whose promo price beats their regular price.

Outputs a markdown digest on stdout and, when GITHUB_OUTPUT is set,
exposes `has_deals`, `title` and `body` for the calling workflow.

Environment:
  KROGER_CLIENT_ID      (required)  API client id
  KROGER_CLIENT_SECRET  (required)  API client secret
  KROGER_ZIP            (required)  ZIP code used to pick a store
  KROGER_LOCATION_ID    (optional)  skip ZIP lookup, use this store id
  KROGER_API_BASE       (optional)  default https://api.kroger.com
  MIN_PERCENT_OFF       (optional)  default 0 -- report every discount
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = os.environ.get("KROGER_API_BASE", "https://api.kroger.com").rstrip("/")
TIMEOUT = 30

# ---------------------------------------------------------------------------
# What we search for.
#
# The Kroger API has no "vegan" flag, so this is term-driven. Every term below
# names a category that is plant-based by definition or by overwhelming
# convention. Anything whose description trips DISALLOWED is dropped; anything
# ambiguous is reported in a separate "check the label" section rather than
# being presented as vegan.
# ---------------------------------------------------------------------------
SEARCH_TERMS = [
    # tofu / tempeh / seitan
    "tofu", "tempeh", "seitan",
    # meat analogues
    "plant based burger", "plant based chicken", "plant based sausage",
    "meatless", "veggie burger", "Beyond Meat", "Impossible",
    "Gardein", "Field Roast", "Tofurky", "Lightlife",
    # milks
    "oat milk", "almond milk", "soy milk", "cashew milk", "coconut milk",
    "Oatly", "Silk", "Califia",
    # yogurt / cheese / butter / cream
    "dairy free yogurt", "vegan cheese", "dairy free cheese",
    "vegan butter", "dairy free creamer",
    "Miyoko", "Violife", "Kite Hill", "Daiya", "Follow Your Heart",
    "So Delicious", "Forager", "Chao",
    # frozen / misc
    "vegan ice cream", "dairy free ice cream", "plant based",
]

# If any of these appear in a product's description, it is not vegan.
DISALLOWED = [
    "milk chocolate", "buttermilk", "whey", "casein", "gelatin",
    "honey", "beef", "pork", "chicken breast", "turkey breast",
    "bacon", "anchov", "gouda", "cheddar cheese", "mozzarella",
    "parmesan", "greek yogurt", "half and half", "heavy cream",
    "egg ", "eggs", "lard", "tallow", "shrimp", "salmon", "tuna",
]

# Brand + description text containing any of these reads as reliably vegan.
CONFIRMING = [
    # explicit labelling
    "vegan", "plant based", "plant-based", "dairy free", "dairy-free",
    "non dairy", "non-dairy", "meatless", "veggie burger",
    # inherently plant-based foods
    "tofu", "tempeh", "seitan",
    # plant milks -- the category name is the confirmation
    "oat milk", "oatmilk", "almond milk", "almondmilk", "soy milk",
    "soymilk", "cashew milk", "coconut milk", "rice milk", "hemp milk",
    "pea milk", "oat beverage", "almond beverage", "soy beverage",
    # brands that are entirely or near-entirely vegan
    "oatly", "miyoko", "violife", "beyond meat", "impossible",
    "gardein", "field roast", "tofurky", "lightlife", "daiya",
    "follow your heart", "so delicious", "forager", "califia",
    "kite hill", "nasoya", "chao",
]


def fail(msg, hint=None):
    print(f"ERROR: {msg}", file=sys.stderr)
    if hint:
        print(f"HINT:  {hint}", file=sys.stderr)
    sys.exit(1)


def request(url, data=None, headers=None, method=None):
    body = data.encode() if isinstance(data, str) else data
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        raise RuntimeError(f"HTTP {e.code} from {url}\n{detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach {url}: {e.reason}") from None


def get_token(client_id, client_secret):
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        payload = request(
            f"{API_BASE}/v1/connect/oauth2/token",
            data=urllib.parse.urlencode(
                {"grant_type": "client_credentials", "scope": "product.compact"}
            ),
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    except RuntimeError as e:
        fail(
            f"token request failed: {e}",
            "A 401 usually means the client id/secret are wrong or belong to a "
            "different environment. If your app is registered under "
            "Certification rather than Production, set the KROGER_API_BASE "
            "variable to https://api-ce.kroger.com.",
        )
    token = payload.get("access_token")
    if not token:
        fail(f"token response had no access_token: {payload}")
    return token


def find_location(token, zip_code):
    url = f"{API_BASE}/v1/locations?" + urllib.parse.urlencode(
        {"filter.zipCode.near": zip_code, "filter.limit": 1}
    )
    data = request(url, headers={"Authorization": f"Bearer {token}"})
    items = data.get("data") or []
    if not items:
        fail(f"no Kroger store found near ZIP {zip_code}")
    store = items[0]
    name = store.get("name", "store")
    addr = (store.get("address") or {}).get("addressLine1", "")
    city = (store.get("address") or {}).get("city", "")
    return store["locationId"], f"{name}, {addr}, {city}".strip(", ")


def search(token, term, location_id):
    url = f"{API_BASE}/v1/products?" + urllib.parse.urlencode(
        {
            "filter.term": term,
            "filter.locationId": location_id,
            "filter.limit": 50,
        }
    )
    try:
        return (request(url, headers={"Authorization": f"Bearer {token}"}).get("data")) or []
    except RuntimeError as e:
        print(f"  warning: search for {term!r} failed: {e}", file=sys.stderr)
        return []


def classify(description, brand=""):
    low = f"{brand} {description}".lower()
    for bad in DISALLOWED:
        if bad in low:
            return "excluded"
    for good in CONFIRMING:
        if good in low:
            return "vegan"
    return "check"


def extract_deals(products, min_percent):
    deals = []
    for p in products:
        desc = p.get("description") or ""
        verdict = classify(desc, p.get("brand") or "")
        if verdict == "excluded":
            continue
        for item in p.get("items") or []:
            price = item.get("price") or {}
            regular = price.get("regular") or 0
            promo = price.get("promo") or 0
            # promo of 0 means "no promotion", not "free"
            if not (regular and promo and promo < regular):
                continue
            pct = round((regular - promo) / regular * 100)
            if pct < min_percent:
                continue
            deals.append(
                {
                    "description": desc,
                    "brand": p.get("brand") or "",
                    "size": item.get("size") or "",
                    "regular": regular,
                    "promo": promo,
                    "percent": pct,
                    "verdict": verdict,
                }
            )
            break
    return deals


def dedupe(deals):
    seen, out = set(), []
    for d in sorted(deals, key=lambda x: -x["percent"]):
        key = (d["description"], d["size"])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def render(deals, store_label, zip_code):
    confirmed = [d for d in deals if d["verdict"] == "vegan"]
    uncertain = [d for d in deals if d["verdict"] == "check"]

    lines = [
        f"Store: **{store_label}** (ZIP {zip_code})",
        "",
        f"{len(confirmed)} plant-based items on sale"
        + (f", plus {len(uncertain)} needing a label check." if uncertain else "."),
        "",
    ]

    def table(rows):
        out = ["| Item | Size | Was | Now | Off |", "|---|---|---|---|---|"]
        for d in rows:
            name = f"{d['brand']} {d['description']}".strip()
            out.append(
                f"| {name} | {d['size']} | ${d['regular']:.2f} | "
                f"${d['promo']:.2f} | {d['percent']}% |"
            )
        return out

    if confirmed:
        lines += table(confirmed) + [""]
    else:
        lines += ["Nothing in the plant-based set is discounted this week.", ""]

    if uncertain:
        lines += [
            "### Check the label",
            "",
            "These matched a plant-based search term but their description "
            "does not confirm it. The Kroger API has no vegan flag, so verify "
            "before buying.",
            "",
        ] + table(uncertain) + [""]

    lines += [
        "---",
        "",
        "Prices are what the Kroger API reported for this store at run time "
        "and can differ at the register. Digital-coupon savings are not "
        "included.",
    ]
    return "\n".join(lines)


def main():
    client_id = os.environ.get("KROGER_CLIENT_ID")
    client_secret = os.environ.get("KROGER_CLIENT_SECRET")
    zip_code = os.environ.get("KROGER_ZIP")
    location_id = os.environ.get("KROGER_LOCATION_ID") or ""
    min_percent = int(os.environ.get("MIN_PERCENT_OFF") or 0)

    if not client_id or not client_secret:
        fail(
            "KROGER_CLIENT_ID and KROGER_CLIENT_SECRET must be set",
            "Add them under Settings -> Secrets and variables -> Actions.",
        )
    if not zip_code and not location_id:
        fail(
            "set KROGER_ZIP (or KROGER_LOCATION_ID)",
            "Add KROGER_ZIP under Settings -> Secrets and variables -> "
            "Actions -> Variables.",
        )

    token = get_token(client_id, client_secret)

    if location_id:
        store_label = f"location {location_id}"
    else:
        location_id, store_label = find_location(token, zip_code)
    print(f"Store: {store_label} ({location_id})", file=sys.stderr)

    products = []
    for term in SEARCH_TERMS:
        found = search(token, term, location_id)
        print(f"  {term}: {len(found)}", file=sys.stderr)
        products.extend(found)
        time.sleep(0.2)

    deals = dedupe(extract_deals(products, min_percent))
    body = render(deals, store_label, zip_code or location_id)
    print(body)

    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        confirmed = sum(1 for d in deals if d["verdict"] == "vegan")
        title = (
            f"Kroger plant-based sales — {confirmed} item"
            f"{'' if confirmed == 1 else 's'} on sale"
        )
        with open(out_path, "a") as fh:
            fh.write(f"has_deals={'true' if deals else 'false'}\n")
            fh.write(f"title={title}\n")
            fh.write("body<<KROGER_EOF\n" + body + "\nKROGER_EOF\n")


if __name__ == "__main__":
    main()
