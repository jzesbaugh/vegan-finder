# Kroger plant-based sale watch

A GitHub Action that checks your Kroger store once a week for discounted
plant-based groceries and opens an issue with what it found. GitHub emails
you when an issue is opened in your own repo, so the issue *is* the email.

It exists because the Kroger API is unreachable from some sandboxed
environments. GitHub's runners have ordinary internet access, so the check
runs there instead.

## What it looks at

Meat analogues, plant milks, plant yogurts and cheeses, vegan butter and
creamers, tofu, tempeh, seitan, and dairy-free frozen desserts — the
substitute aisle, where prices are high and sales actually matter.

An item is reported when the API returns a `promo` price below its
`regular` price for your store. A `promo` of `0` means "no promotion" and
is correctly ignored.

## Setup

**1.** Create a new **private** repository and put these files in it.

**2.** Add your API credentials under
*Settings → Secrets and variables → Actions → **Secrets***:

| Secret | Value |
|---|---|
| `KROGER_CLIENT_ID` | your client id |
| `KROGER_CLIENT_SECRET` | your client secret |

**3.** Add your store under the **Variables** tab on that same page:

| Variable | Value |
|---|---|
| `KROGER_ZIP` | your ZIP code — required |
| `KROGER_LOCATION_ID` | optional; skips the ZIP lookup once you know your store id |
| `KROGER_API_BASE` | optional; set to `https://api-ce.kroger.com` if your app is registered under Certification rather than Production |
| `MIN_PERCENT_OFF` | optional; e.g. `20` to only hear about real markdowns |

**4.** Open the **Actions** tab, pick *Weekly Kroger plant-based sales*, and
click **Run workflow** to test it now rather than waiting for Sunday.

The first successful run prints your resolved store and its `locationId` in
the log. Copy that into `KROGER_LOCATION_ID` to make later runs faster and
immune to the store-lookup rate limit.

## Schedule

Sundays at 13:00 UTC (6am Pacific in summer, 5am in winter). Change the
`cron` line in `.github/workflows/weekly-vegan-sales.yml` to move it.
GitHub may delay scheduled runs by a few minutes to an hour under load.

## About the vegan filtering

The Kroger API has no vegan flag, so the script works by searching
plant-based terms and then filtering descriptions. Two lists in
`scripts/check_sales.py` do the work:

- `DISALLOWED` — animal-derived words that drop an item outright.
- `CONFIRMING` — words and brands that confirm an item is plant-based.

Anything that matches neither goes into a separate **Check the label**
section rather than being presented as vegan. This is deliberate: a
false negative costs you a deal, a false positive costs you more.

Both lists are meant to be edited. If something wrong slips through, add
the word to `DISALLOWED` and it will not appear again.

## Running the tests

    python3 tests/test_check.py

The tests use mocked API responses, so they need no network and no
credentials. They cover the cases most likely to hurt: dairy and honey
being filtered out, `promo: 0` not being read as a sale, duplicate
listings collapsing, and ambiguous items landing in the right bucket.

## Rate limits

Kroger allows 10,000 product calls and 1,600 location calls per day. One
run makes about 35 product calls and at most one location call.

## Re-running it on demand

Three ways, no terminal needed:

1. **Actions tab → Run workflow.** Works on the GitHub website and in the
   GitHub Mobile app (Repository → Actions → Workflows).
2. **Reply `/check` to the digest email.** GitHub turns email replies into
   issue comments, and a `/check` comment from the repo owner re-runs the
   workflow. It reacts 👀 to your comment so you know it heard you.
3. **Comment `/check`** on any issue in the repo from the web UI.

Only the repo owner can trigger it by comment, so a stray comment cannot
burn your API quota.
