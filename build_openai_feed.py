#!/usr/bin/env python3
"""
Green Go Energy: Google Merchant XML (CTX Feed)  ->  OpenAI / ChatGPT Ads product feed (CSV, OpenAI format)

Usage:
  python3 build_openai_feed.py                       # fetch live XML, write products.csv + report.txt
  python3 build_openai_feed.py --xml local.xml       # use a local copy of the XML
  python3 build_openai_feed.py --labels labels.csv   # optional: item_id,custom_label_0  (product groups A-D)
  python3 build_openai_feed.py --out /path/products.csv

Spec: https://developers.openai.com/commerce/specs/file-upload/products  (OpenAI format, stable)
Ads:  https://developers.openai.com/ads/product-feeds
"""
import argparse, csv, re, sys, urllib.parse, urllib.request, collections, datetime
import xml.etree.ElementTree as ET

FEED_URL   = "https://greengoenergy.co.il/wp-content/uploads/woo-feed/google/xml/newmappingproducts.xml"
SELLER     = "Green Go Energy"
SELLER_URL = "https://greengoenergy.co.il"
RETURN_URL = "https://greengoenergy.co.il/terms-of-use/"   # "החזרות וביטולים" section lives on this page
CURRENCY   = "ILS"
# custom-built batteries are non-returnable per the site terms -> leave accepts_returns unspecified for this category
NO_RETURN_PREFIXES = ("סוללות ליתיום",)
DEFAULT_BRAND = "Green Go Energy"
# brand derived from product_type / title when a manufacturer is explicit. Order matters.
BRAND_RULES = [
    ("samsung sdi", "Samsung SDI"),
    ("samsung",     "Samsung SDI"),
    ("molicel",     "Molicel"),
    ("panasonic",   "Panasonic"),
]
NS = {"g": "http://base.google.com/ns/1.0"}

COLUMNS = ["item_id","group_id","listing_has_variations","variant_dict","title","description","url",
           "brand","seller_name","seller_url","image_url","additional_image_urls","price","sale_price",
           "availability","condition","product_category","accepts_returns","return_policy","is_ads_eligible","ads_metadata"]

def txt(it, tag):
    e = it.find("g:" + tag, NS)
    if e is None:
        e = it.find(tag)
    return (e.text or "").strip() if e is not None and e.text else ""

def money(s):
    """'1,399.00 ILS' -> ('1399.00 ILS', 1399.0)"""
    s = s.strip()
    if not s:
        return "", None
    m = re.match(r"^([\d,]+(?:\.\d+)?)\s+([A-Z]{3})$", s)
    if not m:
        return "", None
    amt = float(m.group(1).replace(",", ""))
    return f"{amt:.2f} {m.group(2)}", amt

def enc_url(u):
    """percent-encode non-ASCII / spaces in path+query, keep existing encoding."""
    u = u.strip()
    if not u:
        return ""
    p = urllib.parse.urlsplit(u)
    path  = urllib.parse.quote(p.path, safe="/%:@+~-._")
    query = urllib.parse.quote(p.query, safe="=&%+:@~-._")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, query, ""))

def clean_text(s, limit):
    s = s.replace("&nbsp;", " ").replace(" ", " ")
    s = re.sub(r"<[^>]+>", " ", s)             # stray tags
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s).strip()
    return s[:limit].rstrip()

def brand_for(product_type, title):
    hay = (product_type + " " + title).lower()
    for needle, brand in BRAND_RULES:
        if needle in hay:
            return brand
    return DEFAULT_BRAND

def variant_dict_from_link(link, title):
    q = urllib.parse.urlsplit(link).query
    d = {}
    for k, v in urllib.parse.parse_qsl(q, keep_blank_values=True):
        if k.startswith("attribute_"):
            key = urllib.parse.unquote(k[len("attribute_"):]).replace("-", " ").strip()
            val = urllib.parse.unquote(v).replace("+", " ").strip()
            if key and val:
                d[key] = val
    if not d and " - " in title:
        d["option"] = title.rsplit(" - ", 1)[1].strip()
    return d

def json_obj(d):
    import json
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", help="local XML path (default: fetch live)")
    ap.add_argument("--out", default="products.csv")
    ap.add_argument("--report", default="report.txt")
    ap.add_argument("--labels", help="CSV with item_id,custom_label_0 (optional)")
    ap.add_argument("--skip-out-of-stock", action="store_true",
                    help="drop out_of_stock rows instead of sending them with availability=out_of_stock")
    a = ap.parse_args()

    raw = open(a.xml, "rb").read() if a.xml else urllib.request.urlopen(FEED_URL, timeout=60).read()
    items = ET.fromstring(raw).findall(".//item")

    labels = {}
    if a.labels:
        with open(a.labels, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("item_id") and r.get("custom_label_0"):
                    labels[r["item_id"].strip()] = r["custom_label_0"].strip()

    # group bookkeeping (variants)
    groups = collections.defaultdict(list)
    for it in items:
        groups[txt(it, "item_group_id")].append(it)
    group_desc = {}
    for gid, members in groups.items():
        for m in members:
            if clean_text(txt(m, "description"), 5000):
                group_desc[gid] = txt(m, "description"); break

    rows, rep = [], collections.Counter()
    problems = []
    for it in items:
        iid   = txt(it, "id")
        gid   = txt(it, "item_group_id")
        title = clean_text(txt(it, "title"), 150)
        link  = txt(it, "link")
        ptype = txt(it, "product_type")
        avail = txt(it, "availability")
        desc  = clean_text(txt(it, "description"), 5000) or clean_text(group_desc.get(gid, ""), 5000)
        if not desc:
            desc = f"{title}. {ptype.replace(' > ', ', ')}" if ptype else title
            rep["description_fallback"] += 1

        price_s, price_v = money(txt(it, "price"))
        if price_s and not price_s.endswith(" " + CURRENCY):
            problems.append((iid, "currency is not " + CURRENCY, price_s)); rep["rejected"] += 1; continue
        sale_s, sale_v   = money(txt(it, "sale_price"))
        if sale_v is None or price_v is None or sale_v <= 0 or sale_v >= price_v:
            sale_s = ""
        else:
            rep["with_real_sale_price"] += 1
        if "," in txt(it, "price"):
            rep["price_thousands_separator_fixed"] += 1

        if not iid or not title or not link or not price_v or price_v <= 0 or avail not in ("in_stock","out_of_stock","preorder","backorder"):
            problems.append((iid, "missing required / invalid", title[:50])); rep["rejected"] += 1; continue
        if avail == "out_of_stock":
            rep["out_of_stock"] += 1
            if a.skip_out_of_stock:
                continue
        if avail == "preorder":
            avail = "pre_order"

        image = enc_url(txt(it, "image_link"))
        if not image:
            problems.append((iid, "no image", title[:50])); rep["rejected"] += 1; continue
        if re.search(r"[^\x00-\x7f]", txt(it, "image_link")):
            rep["image_url_encoded"] += 1
        addl = [enc_url(e.text) for e in it.findall("g:additional_image_link", NS) if e is not None and e.text and e.text.strip()]

        is_variant = len(groups[gid]) > 1 and gid != iid
        row = {
            "item_id": iid,
            "group_id": gid if is_variant else "",
            "listing_has_variations": "true" if is_variant else "",
            "variant_dict": json_obj(variant_dict_from_link(link, title)) if is_variant else "",
            "title": title,
            "description": desc,
            "url": link,
            "brand": brand_for(ptype, title),
            "seller_name": SELLER,
            "seller_url": SELLER_URL,
            "image_url": image,
            "additional_image_urls": ",".join(addl),
            "price": price_s,
            "sale_price": sale_s,
            "availability": avail,
            "condition": txt(it, "condition") or "new",
            "product_category": ptype,
            "accepts_returns": "" if ptype.startswith(NO_RETURN_PREFIXES) else "true",
            "return_policy": RETURN_URL,
            "is_ads_eligible": "true",
            "ads_metadata": json_obj({"custom_label_0": labels[iid]}) if iid in labels else "",
        }
        if is_variant: rep["variant_rows"] += 1
        rep["brand_" + row["brand"]] += 1
        rows.append(row)

    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writeheader(); w.writerows(rows)

    with open(a.report, "w", encoding="utf-8") as f:
        f.write(f"built: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n")
        f.write(f"source items: {len(items)}\nrows written: {len(rows)}\n")
        for k, v in sorted(rep.items()): f.write(f"{k}: {v}\n")
        if problems:
            f.write("\nrejected rows:\n")
            for p in problems: f.write(f"  {p}\n")
    print(open(a.report, encoding="utf-8").read())

if __name__ == "__main__":
    main()
