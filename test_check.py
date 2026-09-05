import os, sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
os.environ.update(KROGER_CLIENT_ID="x", KROGER_CLIENT_SECRET="y", KROGER_ZIP="97214")
import check_sales as cs

products = [
  # on sale, clearly vegan
  {"description":"Oat Milk Original","brand":"Oatly",
   "items":[{"size":"64 fl oz","price":{"regular":5.49,"promo":3.99}}]},
  # on sale but NOT vegan -> must be excluded
  {"description":"Sharp Cheddar Cheese Block","brand":"Kroger",
   "items":[{"size":"8 oz","price":{"regular":4.99,"promo":2.99}}]},
  # promo == 0 means no promotion -> must NOT be reported as free
  {"description":"Extra Firm Tofu","brand":"Nasoya",
   "items":[{"size":"14 oz","price":{"regular":2.79,"promo":0}}]},
  # coconut milk IS vegan -> should be confirmed, not flagged
  {"description":"Coconut Milk Beverage","brand":"Generic",
   "items":[{"size":"32 oz","price":{"regular":3.99,"promo":2.50}}]},
  # genuinely ambiguous: matched a search term, nothing confirms or excludes
  {"description":"Garlic Herb Spread","brand":"Generic",
   "items":[{"size":"6 oz","price":{"regular":4.49,"promo":3.49}}]},
  # honey trap -> excluded despite plant-based term
  {"description":"Plant Based Honey Nut Granola","brand":"X",
   "items":[{"size":"12 oz","price":{"regular":6.00,"promo":4.00}}]},
  # duplicate of the Oatly entry -> must dedupe
  {"description":"Oat Milk Original","brand":"Oatly",
   "items":[{"size":"64 fl oz","price":{"regular":5.49,"promo":3.99}}]},
  # no promo key at all
  {"description":"Vegan Butter Sticks","brand":"Miyoko",
   "items":[{"size":"8 oz","price":{"regular":7.49}}]},
]

deals = cs.dedupe(cs.extract_deals(products, 0))
print("=== deals ===")
for d in deals:
    print(f"  {d['verdict']:8} {d['brand']} {d['description']} "
          f"{d['regular']}->{d['promo']} ({d['percent']}%)")

names = [d["description"] for d in deals]
assert "Sharp Cheddar Cheese Block" not in names, "FAIL: dairy leaked through"
assert "Plant Based Honey Nut Granola" not in names, "FAIL: honey leaked through"
assert "Extra Firm Tofu" not in names, "FAIL: promo=0 treated as a sale"
assert "Vegan Butter Sticks" not in names, "FAIL: missing promo treated as a sale"
assert names.count("Oat Milk Original") == 1, "FAIL: dedupe broken"
assert [d for d in deals if d["description"]=="Coconut Milk Beverage"][0]["verdict"]=="vegan"
assert [d for d in deals if d["description"]=="Garlic Herb Spread"][0]["verdict"]=="check"
assert [d for d in deals if d["description"]=="Oat Milk Original"][0]["verdict"]=="vegan"
assert deals[0]["percent"] >= deals[-1]["percent"], "FAIL: not sorted by discount"

# min-percent gate
assert len(cs.dedupe(cs.extract_deals(products, 30))) < len(deals), "FAIL: min_percent gate"

print("\n=== rendered digest ===")
print(cs.render(deals, "Kroger Hawthorne, 3030 SE Hawthorne Blvd, Portland", "97214"))
print("\nALL ASSERTIONS PASSED")
