"""Google Merchant Center feed of printara.co marketplace models (digital STL/3MF/SVG files).
Reads sitemap-models.xml, takes the Product JSON-LD of each model page.
Run: python -I build_marketplace_feed.py -> google_feed_marketplace.tsv"""
import csv, json, os, re, urllib.request, concurrent.futures as cf
OUT = os.environ.get("FEED_OUT") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT, exist_ok=True)
MIN_ROWS = int(os.environ.get("FEED_MIN_ROWS", "0"))
UA = {"User-Agent": "printara-feed-builder"}
def get(u): return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read().decode("utf-8", "replace")
urls = re.findall(r"<loc>([^<]+)</loc>", get("https://printara.co/sitemap-models.xml"))
def one(u):
    try: h = get(u)
    except Exception as e: return ("ERR", u, str(e))
    for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        try: d = json.loads(m)
        except Exception: continue
        if d.get("@type") == "Product":
            o = d.get("offers") or {}
            if isinstance(o, list): o = o[0]
            return ("OK", u, d, o)
    return ("NOPRODUCT", u, None)
rows, bad = [], []
with cf.ThreadPoolExecutor(8) as ex:
    for r in ex.map(one, urls):
        if r[0] != "OK": bad.append(r[:3]); continue
        _, u, d, o = r
        try: price = float(o.get("price"))
        except Exception: bad.append(("NOPRICE", u, o.get("price"))); continue
        if price <= 0 or "InStock" not in str(o.get("availability", "")): bad.append(("FREE_OR_OOS", u, price)); continue
        imgs = d.get("image") or []; imgs = [imgs] if isinstance(imgs, str) else imgs
        if not imgs: bad.append(("NOIMG", u, "")); continue
        seller = (o.get("seller") or {}).get("name", "")
        title = re.sub(r"\s+", " ", d["name"]).strip()
        desc = re.sub(r"\s+", " ", d.get("description") or title).strip()
        desc = f"Digital download (3D printable file) sold on the Printara marketplace{' by ' + seller if seller else ''}. {desc}"
        rows.append([d.get("sku") or u.rsplit("-", 5)[-5:], title[:150], desc[:5000], u, imgs[0], ",".join(imgs[1:10]),
                     f"{price:.2f} {o.get('priceCurrency','USD')}", "in_stock", "new", "Printara", "no",
                     "Toys & Games > Toys > Model Building Kits", "digital_download", seller, "US:::0.00 USD", "no"])
if len(rows) < MIN_ROWS:
    raise SystemExit(f"only {len(rows)} rows (< {MIN_ROWS}), keeping the old feed")
head = ["id","title","description","link","image_link","additional_image_link","price","availability","condition","brand","identifier_exists","google_product_category","custom_label_0","custom_label_1","shipping","adult"]
with open(os.path.join(OUT, "google_feed_marketplace.tsv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter="\t"); w.writerow(head); w.writerows(rows)
with open(os.path.join(OUT, "marketplace_skipped.json"), "w", encoding="utf-8") as f: json.dump(bad, f, ensure_ascii=False, indent=1)
from collections import Counter
print("urls", len(urls), "| feed rows", len(rows), "| skipped", Counter(b[0] for b in bad))
print("currencies", Counter(r[6].split()[1] for r in rows), "| sellers", Counter(r[13] for r in rows).most_common(10))
ps = sorted(float(r[6].split()[0]) for r in rows); print("price min/median/max", ps[0], ps[len(ps)//2], ps[-1])
