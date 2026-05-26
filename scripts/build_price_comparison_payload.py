"""
Build site/data/price_comparison_payload.json from brand_extractions (Neon DIP).

Usage (Railway):
    railway run python scripts/build_price_comparison_payload.py

Quality filter:
  - dispensary universe = state ∈ {IL,NJ,NY} AND is_aggregator_website=false AND ≥5 priced rows on its menu (any brand)
Promo logic:
  - is_on_promo row-level: price_numeric < reg_price_numeric AND reg_price_numeric IS NOT NULL
  - effective_price = price_numeric
  - regular_price  = COALESCE(reg_price_numeric, price_numeric)
  - promo_participation_pct = (on-promo rows) / (TOTAL rows)
      NB: in DIP today reg_price_numeric is only populated on promo'd rows (it acts
      as a promo flag, not a list price). So denominator = total rows gives the
      meaningful "% of observations discounted" that the UI methodology blurb describes.
  - avg_promo_discount_pct  = AVG(discount_pct) over on-promo rows only
SKU partition: (brand_canonical, normalized product_type, weight_g | size_mg)
"""
import json
import os
import sys
import datetime as dt
from collections import defaultdict
from statistics import median

import psycopg2
import psycopg2.extras


SKUS = [
    # default tabs
    {"key": "select-2g-vape",            "brand": "select",     "brand_display": "Select",     "ptype": "vape",        "size_field": "weight_g", "size_val": 2.0,   "label": "Select 2g vape",                "group": "default"},
    {"key": "grassroots-3.5g-flower",    "brand": "grassroots", "brand_display": "Grassroots", "ptype": "flower",      "size_field": "weight_g", "size_val": 3.5,   "label": "Grassroots 3.5g flower",        "group": "default"},
    {"key": "find-3.5g-flower",          "brand": "find",       "brand_display": "Find",       "ptype": "flower",      "size_field": "weight_g", "size_val": 3.5,   "label": "Find 3.5g flower",              "group": "default"},
    {"key": "anthem-1g-preroll",         "brand": "anthem",     "brand_display": "Anthem",     "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 1.0,   "label": "Anthem 1g pre-roll",            "group": "default"},
    {"key": "jams-100mg-edible",         "brand": "jams",       "brand_display": "JAMS",       "ptype": "edible",      "size_field": "size_mg",  "size_val": 100.0, "label": "JAMS 100mg edible",             "group": "default"},
    # dropdown: Select
    {"key": "select-1g-vape",            "brand": "select",     "brand_display": "Select",     "ptype": "vape",        "size_field": "weight_g", "size_val": 1.0,   "label": "Select 1g vape",                "group": "Select"},
    {"key": "select-100mg-edible",       "brand": "select",     "brand_display": "Select",     "ptype": "edible",      "size_field": "size_mg",  "size_val": 100.0, "label": "Select 100mg edible",           "group": "Select"},
    # dropdown: Grassroots
    {"key": "grassroots-7g-flower",      "brand": "grassroots", "brand_display": "Grassroots", "ptype": "flower",      "size_field": "weight_g", "size_val": 7.0,   "label": "Grassroots 7g flower",          "group": "Grassroots"},
    {"key": "grassroots-14g-flower",     "brand": "grassroots", "brand_display": "Grassroots", "ptype": "flower",      "size_field": "weight_g", "size_val": 14.0,  "label": "Grassroots 14g flower",         "group": "Grassroots"},
    {"key": "grassroots-1g-preroll",     "brand": "grassroots", "brand_display": "Grassroots", "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 1.0,   "label": "Grassroots 1g pre-roll",        "group": "Grassroots"},
    {"key": "grassroots-2g-preroll",     "brand": "grassroots", "brand_display": "Grassroots", "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 2.0,   "label": "Grassroots 2g pre-roll",        "group": "Grassroots"},
    {"key": "grassroots-1g-concentrate", "brand": "grassroots", "brand_display": "Grassroots", "ptype": "concentrate", "size_field": "weight_g", "size_val": 1.0,   "label": "Grassroots 1g concentrate",     "group": "Grassroots"},
    {"key": "grassroots-0.5g-concentrate","brand":"grassroots", "brand_display": "Grassroots", "ptype": "concentrate", "size_field": "weight_g", "size_val": 0.5,   "label": "Grassroots 0.5g concentrate",   "group": "Grassroots"},
    # dropdown: Find
    {"key": "find-1g-preroll",           "brand": "find",       "brand_display": "Find",       "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 1.0,   "label": "Find 1g pre-roll",              "group": "Find"},
    {"key": "find-7g-flower",            "brand": "find",       "brand_display": "Find",       "ptype": "flower",      "size_field": "weight_g", "size_val": 7.0,   "label": "Find 7g flower",                "group": "Find"},
    {"key": "find-14g-flower",           "brand": "find",       "brand_display": "Find",       "ptype": "flower",      "size_field": "weight_g", "size_val": 14.0,  "label": "Find 14g flower",               "group": "Find"},
    {"key": "find-28g-flower",           "brand": "find",       "brand_display": "Find",       "ptype": "flower",      "size_field": "weight_g", "size_val": 28.0,  "label": "Find 28g flower",               "group": "Find"},
    {"key": "find-70g-flower",           "brand": "find",       "brand_display": "Find",       "ptype": "flower",      "size_field": "weight_g", "size_val": 70.0,  "label": "Find 70g flower",               "group": "Find"},
    {"key": "find-10g-preroll",          "brand": "find",       "brand_display": "Find",       "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 10.0,  "label": "Find 10g pre-roll",             "group": "Find"},
    # dropdown: Anthem
    {"key": "anthem-3.5g-preroll",       "brand": "anthem",     "brand_display": "Anthem",     "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 3.5,   "label": "Anthem 3.5g pre-roll",          "group": "Anthem"},
    {"key": "anthem-2.5g-preroll",       "brand": "anthem",     "brand_display": "Anthem",     "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 2.5,   "label": "Anthem 2.5g pre-roll",          "group": "Anthem"},
    {"key": "anthem-5g-preroll",         "brand": "anthem",     "brand_display": "Anthem",     "ptype": "pre-roll",    "size_field": "weight_g", "size_val": 5.0,   "label": "Anthem 5g pre-roll",            "group": "Anthem"},
]

STATES = ["IL", "NJ", "NY"]


# Brand canonical filter — collapses curaleaf_select into select
BRAND_FILTER = {
    "select":     "LOWER(brand_canonical) IN ('select','curaleaf_select')",
    "grassroots": "LOWER(brand_canonical) = 'grassroots'",
    "find":       "LOWER(brand_canonical) = 'find'",
    "anthem":     "LOWER(brand_canonical) = 'anthem'",
    "jams":       "LOWER(brand_canonical) = 'jams'",
}

# Normalized product_type buckets — same logic as we used in Neon probing
PTYPE_FILTERS = {
    "pre-roll":    "(product_type ILIKE '%pre%roll%' OR product_type ILIKE 'preroll%')",
    "vape":        "(product_type ILIKE '%vape%' OR product_type ILIKE '%cartridge%' OR product_type ILIKE '%disposable%' OR product_type ILIKE 'briq%' OR product_type ILIKE '%pen%')",
    "concentrate": "(product_type ILIKE '%concentrate%' OR product_type ILIKE 'extract' OR product_type ILIKE '%budder%' OR product_type ILIKE '%crumble%' OR product_type ILIKE '%sugar%' OR product_type ILIKE '%diamond%' OR product_type ILIKE '%rso%' OR product_type ILIKE '%distillate%')",
    "flower":      "(product_type ILIKE '%flower%' OR product_type ILIKE '%popcorn%' OR product_type ILIKE '%bud%' OR product_type ILIKE '%shake%' OR product_type ILIKE '%smalls%')",
    "edible":      "(product_type ILIKE '%edible%' OR product_type ILIKE '%gumm%' OR product_type ILIKE '%jell%')",
}


def med(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return round(median(xs), 2)


def pct(num, denom):
    if not denom:
        return None
    return round(100.0 * num / denom, 1)


def fetch_rows(conn, sku, state):
    """Pull all priced rows for this SKU × state from qualified dispensaries.
    Returns list of dicts with one row per priced observation.
    Quality filter: disp must be non-aggregator AND have ≥5 priced rows on its menu.
    """
    brand_clause = BRAND_FILTER[sku["brand"]]
    ptype_clause = PTYPE_FILTERS[sku["ptype"]]
    size_clause = f"{sku['size_field']} = %(size_val)s"

    sql = f"""
        WITH qualified AS (
            SELECT d.id, d.name, d.chain_name
            FROM dispensaries d
            WHERE d.state = %(state)s
              AND COALESCE(d.is_aggregator_website, false) = false
              AND (
                SELECT COUNT(*) FROM brand_extractions be2
                WHERE be2.dispensary_id = d.id AND be2.price_numeric IS NOT NULL
              ) >= 5
        )
        SELECT
            q.id            AS dispensary_id,
            q.name          AS dispensary_name,
            q.chain_name    AS chain_name,
            be.price_numeric,
            be.reg_price_numeric,
            be.discount_pct
        FROM qualified q
        JOIN brand_extractions be ON be.dispensary_id = q.id
        WHERE be.price_numeric IS NOT NULL
          AND {brand_clause}
          AND {ptype_clause}
          AND {size_clause}
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, {"state": state, "size_val": sku["size_val"]})
        return cur.fetchall()


def is_curaleaf(chain_name):
    return chain_name is not None and "curaleaf" in chain_name.lower()


def build_state_bucket(rows, sku):
    """Take raw rows for (sku, state), return the state bucket dict per locked schema."""
    own = [r for r in rows if is_curaleaf(r["chain_name"])]
    mkt = [r for r in rows if not is_curaleaf(r["chain_name"])]

    # --- anchor ---
    curaleaf_anchor = None
    if own:
        own_disps = {r["dispensary_id"] for r in own}
        eff_prices = [r["price_numeric"] for r in own]
        reg_prices = [(r["reg_price_numeric"] if r["reg_price_numeric"] is not None else r["price_numeric"]) for r in own]
        curaleaf_anchor = {
            "n_stores":         len(own_disps),
            "median_effective": med(eff_prices),
            "median_regular":   med(reg_prices),
            "min_effective":    round(min(eff_prices), 2) if eff_prices else None,
            "max_effective":    round(max(eff_prices), 2) if eff_prices else None,
        }

    # --- market aggregates ---
    market = None
    if mkt:
        eff_prices = [r["price_numeric"] for r in mkt]
        reg_prices = [(r["reg_price_numeric"] if r["reg_price_numeric"] is not None else r["price_numeric"]) for r in mkt]
        on_promo_rows = [r for r in mkt
                         if r["reg_price_numeric"] is not None
                         and r["price_numeric"] < r["reg_price_numeric"]]
        promo_part = pct(len(on_promo_rows), len(mkt))
        promo_disc = None
        if on_promo_rows:
            discs = [r["discount_pct"] for r in on_promo_rows if r["discount_pct"] is not None]
            if discs:
                promo_disc = round(sum(discs) / len(discs), 1)
            else:
                # fall back to computing from regular/effective when discount_pct missing
                comp = [100.0 * (r["reg_price_numeric"] - r["price_numeric"]) / r["reg_price_numeric"]
                        for r in on_promo_rows if r["reg_price_numeric"]]
                promo_disc = round(sum(comp) / len(comp), 1) if comp else None
        market = {
            "n_retailers":             len({r["dispensary_id"] for r in mkt}),
            "n_observations":          len(mkt),
            "median_regular":          med(reg_prices),
            "median_effective":        med(eff_prices),
            "min_effective":           round(min(eff_prices), 2) if eff_prices else None,
            "max_effective":           round(max(eff_prices), 2) if eff_prices else None,
            "promo_participation_pct": promo_part,
            "avg_promo_discount_pct":  promo_disc,
        }

    # --- per-retailer detail (market disps only) ---
    by_disp = defaultdict(list)
    for r in mkt:
        by_disp[(r["dispensary_id"], r["dispensary_name"])].append(r)

    anchor_eff = curaleaf_anchor["median_effective"] if curaleaf_anchor else None
    retailers = []
    for (disp_id, disp_name), rs in by_disp.items():
        eff = [r["price_numeric"] for r in rs]
        reg = [(r["reg_price_numeric"] if r["reg_price_numeric"] is not None else r["price_numeric"]) for r in rs]
        on_promo = any(r["reg_price_numeric"] is not None and r["price_numeric"] < r["reg_price_numeric"] for r in rs)
        m_eff = med(eff)
        m_reg = med(reg)
        retailers.append({
            "dispensary_id":           disp_id,
            "dispensary_name":         disp_name,
            "n_observations":          len(rs),
            "median_regular":          m_reg,
            "median_effective":        m_eff,
            "is_on_promo":             on_promo,
            "vs_anchor_pct_effective": round(100.0 * (m_eff - anchor_eff) / anchor_eff, 1) if anchor_eff and m_eff is not None else None,
            "vs_anchor_pct_regular":   round(100.0 * (m_reg - anchor_eff) / anchor_eff, 1) if anchor_eff and m_reg is not None else None,
        })

    retailers.sort(key=lambda r: (
        r["vs_anchor_pct_effective"] if r["vs_anchor_pct_effective"] is not None else float("inf"),
        -r["n_observations"],
    ))

    return {"curaleaf_anchor": curaleaf_anchor, "market": market, "retailers": retailers}


def iso_week(today):
    yr, wk, _ = today.isocalendar()
    return f"W{wk:02d}"


def main():
    dsn = os.environ.get("DIP_DATABASE_URL")
    if not dsn:
        sys.stderr.write("ERROR: DIP_DATABASE_URL not set. Run via `railway run`.\n")
        sys.exit(1)

    today = dt.datetime.now(dt.timezone.utc)
    conn = psycopg2.connect(dsn)
    skus_out = []
    retailer_counts = {}

    try:
        for sku in SKUS:
            states_bucket = {}
            for state in STATES:
                rows = fetch_rows(conn, sku, state)
                states_bucket[state] = build_state_bucket(rows, sku) if rows else {"curaleaf_anchor": None, "market": None, "retailers": []}
            n_ret = sum(
                states_bucket[s]["market"]["n_retailers"] if states_bucket[s]["market"] else 0
                for s in STATES
            )
            retailer_counts[sku["key"]] = n_ret
            skus_out.append({
                "key":           sku["key"],
                "brand":         sku["brand"],
                "brand_display": sku["brand_display"],
                "product_type":  sku["ptype"],
                "size_norm":     f"{sku['size_val']}{'g' if sku['size_field']=='weight_g' else 'mg'}",
                "label":         sku["label"],
                "n_retailers_total": n_ret,
                "states":        states_bucket,
            })
    finally:
        conn.close()

    # Dropdown grouping per locked manifest order
    grouped = {"Select": [], "Grassroots": [], "Find": [], "Anthem": []}
    for sku in SKUS:
        if sku["group"] in grouped:
            grouped[sku["group"]].append(sku["key"])
    # within each group, sort by n_retailers_total desc
    for g in grouped:
        grouped[g].sort(key=lambda k: -retailer_counts.get(k, 0))

    payload = {
        "manifest": {
            "default_tabs": [s["key"] for s in SKUS if s["group"] == "default"],
            "dropdown_grouped": grouped,
            "generated_at":   today.isoformat(timespec="seconds"),
            "data_source":    "brand_extractions",
            "quality_filter": "disps ≥5 priced items, no aggregator websites",
            "week_iso":       iso_week(today),
        },
        "skus": skus_out,
    }

    out_path = os.path.join(os.path.dirname(__file__), "..", "site", "data", "price_comparison_payload.json")
    out_path = os.path.abspath(out_path)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    sys.stdout.write(f"Wrote {out_path}\n")
    sys.stdout.write(f"  SKUs: {len(skus_out)}\n")
    sys.stdout.write(f"  Total retailer rows: {sum(len(s['states'][st]['retailers']) for s in skus_out for st in STATES)}\n")


if __name__ == "__main__":
    main()
