"""Google Merchant Center feed of printara.co marketplace models (digital STL/3MF/SVG files).
Reads sitemap-models.xml, takes the Product JSON-LD of each model page.
Run: python -I build_marketplace_feed.py -> google_feed_marketplace.tsv"""
import csv, json, os, re, urllib.request, concurrent.futures as cf
OUT = os.environ.get("FEED_OUT") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUT, exist_ok=True)
# Third-party franchises and trademarks: Google treats them as counterfeit/IP risk, which can suspend the whole account.
EXCLUDE_IP = re.compile(r"""grinch|monster hand|never sleep again|dream demon|pumpkin king|demonic nun|beagle dog pup|monster energy|red bull|coca.?cola|pepsi|lord of the rings|\blotr\b|esdla|tolkien|hobbit|\bfrodo\b|gandalf|sauron|\bazog\b|gollum|aragorn|legolas|galadriel|celeborn|nazg[uû]l|gil.?galad|bilbo|faramir|radagast|bofur|merry and pippin|mordor|gondor|one piece|pok[eé]mon|gengar|pikachu|witcher|peter griffin|space marine|terminator|alien predator|xenomorph|diablo|ac/dc|angus young|ghostface|\bjoker\b|clown prince|fan art|fan sculpt|fanart|star wars|marvel|disney|harry potter|warhammer|nintendo|zelda|super mario|batman|spider-?man|stranger things|game of thrones|heavily inspired by|strongly inspired by|directly inspired by|inspired by the (?:most )?iconic|inspired by the legendary|middle.?earth|prancing pony|ring bearer|\bdunes?\s*-|atreides|artreides|irulan|\bchani|rabban|fenring|mk scorpion|mortal kombat|sub.?zero|davy jones|ghost of sparta|kratos|god of war|night he came home|michael myers|chainsaw slasher|leatherface|texas chainsaw|jurassic|paddock|maximus|gladiator general|resident evil|dimitrescu|colonial marine|bug hunter|messi|lamine yamal|mustaine|mccartney|beatles|biggie|notorious b|valentino rossi|racing legend|metallica|cliff burton|kurt cobain|haaland|mbapp|ronaldo|cr7|schwarzenegger|king of pop|michael jackson|thriller|smooth criminal|prince of darkness|ozzy|45th us president|trump|irish rock legend|rock legend vocalist|west coast rap|reggae legend|g?lam rock|stage legend|starman|freddie|bowie|tupac|bob marley|bono|hockey mask|camp blood|camp slasher|crystal lake|ghost mask|ghostface|sewer clown|time to float|pennywise|playtime is over|miss me possessed|someone.s always watching|no one escapes|beetlejuice|hocus pocus|sanderson|birmingham gangster|peaky|godfather|mob boss|tulsa|bio.?mutant nemesis|ultimate weapon|the mask movie|green anti.?hero|xeno.?terror|sandworm|desert leviathan|shadow of the island|tsushima|fungal mutant|cordyceps|last of us|horror slasher movie|mystery solving team|scooby|bedrock|flintstone|yabba|dabba|detective rabbit|noir investigator|cartoon rabbit|sun.kissed savior|baywatch|yellow square cartoon|spongebob|cheese enthusiast|wallace|\bkcd\b|kingdom come""", re.I)
MIN_ROWS = int(os.environ.get("FEED_MIN_ROWS", "0"))
# Feed images: files.printara.co serves big PNGs (and JPEGs named .png with image/png), Microsoft MC rejected ~200
# with "image URL issue". When FEED_IMG_DIR is set, each main image is re-encoded once to a real JPEG
# (max 1200 px, ~100-300 kB) in that folder (branch printara-img) and the feed links to raw.githubusercontent.
IMG_DIR = os.environ.get("FEED_IMG_DIR")
IMG_BASE = os.environ.get("FEED_IMG_BASE", "https://raw.githubusercontent.com/faficka/tl-media/printara-img/")
UA = {"User-Agent": "printara-feed-builder"}
# Product videos (Merchant Center Product Studio "Animate images", 8 s 1280x720): printara/videos/printara_<id prefix>_*.mp4,
# served by GitHub Pages as video/mp4 -> [video_link] (max 10 per product, comma-separated in TSV).
VID_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "printara", "videos")
VID_BASE = "https://faficka.github.io/tl-media/printara/videos/"
VIDEOS = {}
for _f in sorted(os.listdir(VID_DIR)) if os.path.isdir(VID_DIR) else []:
    _m = re.match(r"printara_([0-9a-f]{8})_.+\.mp4$", _f)
    if _m: VIDEOS.setdefault(_m.group(1), []).append(VID_BASE + _f)
def videos(pid): return ",".join(VIDEOS.get(str(pid)[:8], [])[:10])
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
# Exact paths from the official Google taxonomy (taxonomy-with-ids.en-US.txt). The old value
# "Toys & Games > Toys > Model Building Kits" is not in the taxonomy -> Pinterest warning 126 on every item.
CATEGORIES = [
    (r"ornament|bauble|christmas tree decor", "Home & Garden > Decor > Seasonal & Holiday Decorations > Holiday Ornaments"),
    (r"\bmask\b|helmet|cosplay", "Apparel & Accessories > Costumes & Accessories > Masks"),
    (r"key ?chain|key ?ring", "Apparel & Accessories > Handbag & Wallet Accessories > Keychains"),
    (r"cookie cutter", "Home & Garden > Kitchen & Dining > Kitchen Tools & Utensils > Cookie Cutters"),
    (r"\bvase\b", "Home & Garden > Decor > Vases"),
    (r"planter|flower ?pot|\bpot\b", "Home & Garden > Lawn & Garden > Gardening > Pots & Planters"),
    (r"lamp|lithophane|night ?light|lantern", "Home & Garden > Lighting > Lamps"),
    (r"bookmark", "Office Supplies > Book Accessories > Bookmarks"),
    (r"laser|\bsvg\b|\bdxf\b|stencil", "Arts & Entertainment > Hobbies & Creative Arts > Arts & Crafts > Art & Crafting Tools > Craft Measuring & Marking Tools > Stencils & Die Cuts"),
    (r"figur|statue|bust|sculpt|miniature|\bmini\b|diorama|terrain|28 ?mm|32 ?mm|75 ?mm|tabletop", "Home & Garden > Decor > Figurines"),
]
def category(title):
    for pat, cat in CATEGORIES:
        if re.search(pat, title, re.I): return cat
    return "Arts & Entertainment > Hobbies & Creative Arts > Model Making > Scale Model Kits"

# 17.11.2026 (owner OK): Google-friendly titles/descriptions built ONLY from the seller's own title/description.
FEAT_TYPES = [("Figurines", "Figurine"), ("Holiday Ornaments", "Ornament"), ("Lamps", "Lamp"), ("Masks", "Mask")]
def is_laser(t): return bool(re.search(r"laser|\bsvg\b|\bdxf\b", t, re.I))
def feats(t, d):
    s = (t + " " + d).lower(); f = set()
    if re.search(r"pre-?supported", s): f.add("presupported")
    if re.search(r"\b3mf\b|\bams\b|multi-?colou?r", s): f.add("3mf")
    return f, list(dict.fromkeys(re.findall(r"\b(\d{2,3})\s?mm\b", t)))
def core(t):
    c = re.split(r"\s[-–|:—]\s|,\s", t)[0]
    c = re.sub(r"\b(3D Print(able|ed)?|STL( Files?)?|3MF|Pre-?Supported|Scalable|All Scales|FDM|SLA|Resin|AMS Ready|Multi-?Colou?r|Laser[- ]?cut( Files?)?|SVG|DXF|File)\b", "", c, flags=re.I)
    c = re.sub(r"\b\d{2,3}\s?mm\b", "", c); c = re.sub(r"\b(and|for|&|\+)\s*$", "", c.strip(), flags=re.I)
    return re.sub(r"\s{2,}", " ", c).strip(" -–|,&+") or t
def g_title(t, d, cat):
    c = core(t); f, mm = feats(t, d)
    if is_laser(t): return f"{c} – Laser Cut File | SVG & DXF Digital Download"[:150]
    if len(c.split()) <= 2:
        for k, n in FEAT_TYPES:
            if k in cat and n.lower() not in c.lower(): c = f"{c} {n}"; break
    tail = ["3D Printable STL File"]
    if "presupported" in f: tail.append("Presupported")
    if "3mf" in f: tail.append("Multicolor AMS 3MF")
    if mm: tail.append(" / ".join(mm) + " mm")
    return (c + " – " + " | ".join(tail))[:150]
def g_desc(t, d, seller):
    f, mm = feats(t, d); c = core(t)
    if is_laser(t): lead = f"Laser cut file (SVG and DXF) of {c}."
    else:
        ex = []
        if "presupported" in f: ex.append("presupported for resin printers")
        if "3mf" in f: ex.append("multicolor 3MF ready for Bambu Lab AMS")
        if mm: ex.append("scaled for " + ", ".join(mm) + " mm")
        lead = f"3D printable STL file of {c}" + (", " + ", ".join(ex) if ex else "") + "."
    lead += " Instant digital download from the Printara marketplace" + (f" by {seller}" if seller else "") + ". "
    return (lead + d)[:5000]
def g_highlights(t, d):
    f, mm = feats(t, d); h = ["Instant digital download after purchase"]
    if is_laser(t): h.append("SVG and DXF files for laser cutters")
    else:
        if "presupported" in f: h.append("Presupported for resin printing")
        if "3mf" in f: h.append("Multicolor 3MF for Bambu Lab AMS")
        if mm: h.append("Scaled for " + " / ".join(mm) + " mm")
    return ",".join(h)
def g_type(t, cat): return ("Digital Downloads > Laser Cut Files > " if is_laser(t) else "Digital Downloads > 3D Printable Files > ") + cat.split(" > ")[-1]
# Digital download = free "shipping" in every target country (US + English-speaking markets since 15.11.2026).
# All shipping values in USD = same currency as price (Google rejects mixed currencies: "Inconsistent currencies", 17.11.2026).
# 17.11.2026: + European countries (English feed, prices auto-converted by Google).
SHIPPING = ",".join(f"{c}:::0.00 USD" for c in ["US","GB","CA","AU","IE","NZ","DE","FR","NL","BE","AT","ES","IT","PT","PL","CZ","SK","SE","DK","FI"])
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
        if EXCLUDE_IP.search(title) or EXCLUDE_IP.search(d.get("description") or ""): bad.append(("IP_EXCLUDED", u, title)); continue
        desc = re.sub(r"\s+", " ", d.get("description") or title).strip()
        cat = category(title)
        rows.append([d.get("sku") or u.rsplit("-", 5)[-5:], g_title(title, desc, cat), g_desc(title, desc, seller), u, imgs[0], ",".join(imgs[1:10]),
                     f"{price:.2f} {o.get('priceCurrency','USD')}", "in_stock", "new", "Printara", "no",
                     cat, "digital_download", seller, SHIPPING, "no", g_type(title, cat), g_highlights(title, desc)])
        rows[-1].append(videos(rows[-1][0]))
def jpg(src):
    import hashlib, io
    name = hashlib.sha1(src.encode()).hexdigest()[:20] + ".jpg"
    path = os.path.join(IMG_DIR, name)
    if not os.path.exists(path):
        from PIL import Image
        raw = urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0 printara-feed-builder"}), timeout=60).read()
        im = Image.open(io.BytesIO(raw))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA"); bg = Image.new("RGB", im.size, (255, 255, 255)); bg.paste(im, mask=im.split()[-1]); im = bg
        im = im.convert("RGB"); im.thumbnail((1200, 1200), Image.LANCZOS)
        im.save(path, "JPEG", quality=84, optimize=True, progressive=True)
    return IMG_BASE + name
if IMG_DIR:
    os.makedirs(IMG_DIR, exist_ok=True)
    def fix(r):
        try: r[4] = jpg(r[4])
        except Exception as e: print("IMG_FAIL", r[3], e)
        return r
    with cf.ThreadPoolExecutor(8) as ex: rows = list(ex.map(fix, rows))
    keep = {r[4].rsplit("/", 1)[-1] for r in rows}
    for f in os.listdir(IMG_DIR):
        if f.endswith(".jpg") and f not in keep: os.remove(os.path.join(IMG_DIR, f))
if len(rows) < MIN_ROWS:
    raise SystemExit(f"only {len(rows)} rows (< {MIN_ROWS}), keeping the old feed")
head = ["id","title","description","link","image_link","additional_image_link","price","availability","condition","brand","identifier_exists","google_product_category","custom_label_0","custom_label_1","shipping","adult","product_type","product_highlight","video_link"]
with open(os.path.join(OUT, "google_feed_marketplace.tsv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter="\t"); w.writerow(head); w.writerows(rows)
with open(os.path.join(OUT, "marketplace_skipped.json"), "w", encoding="utf-8") as f: json.dump(bad, f, ensure_ascii=False, indent=1)
from collections import Counter
print("urls", len(urls), "| feed rows", len(rows), "| skipped", Counter(b[0] for b in bad))
print("currencies", Counter(r[6].split()[1] for r in rows), "| sellers", Counter(r[13] for r in rows).most_common(10))
ps = sorted(float(r[6].split()[0]) for r in rows); print("price min/median/max", ps[0], ps[len(ps)//2], ps[-1])
