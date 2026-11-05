"""Telegram notifications for every Buffer post of Gary Gyoza, Talia Latour and Printara (user, 2026-10-15).

Runs every 10 minutes in GitHub Actions (repo faficka/tl-media, .github/workflows/notify.yml).
- automatic post went out -> "vyšlo" + link; failed -> error message
- notification post is due -> reminder to publish it from the phone (trending sound), with the video link and caption
- 08:00 Prague -> overview of everything due today
Secrets: BUFFER_KEY_GARY, BUFFER_KEY (Talia), BUFFER_KEY_PRINTARA, TELEGRAM_TOKEN, TELEGRAM_CHAT.
State (ids already reported, last summary day) lives in cloud/notify_state.json, committed back by the workflow.
    python3 cloud/notify.py [--dry]
"""
import datetime as dt
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

STATE = Path(__file__).resolve().parent / "notify_state.json"
PRAGUE = ZoneInfo("Europe/Prague")
BRANDS = {"GARY": "BUFFER_KEY_GARY", "TALIA": "BUFFER_KEY", "PRINTARA": "BUFFER_KEY_PRINTARA"}
SERVICE = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube", "pinterest": "Pinterest"}


def gql(key, query, variables=None):
    req = urllib.request.Request("https://api.buffer.com",
                                 data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                          "User-Agent": "astra-notify/1.0"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        sys.exit(f"Buffer HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    if "errors" in r:
        sys.exit(f"Buffer error: {r['errors']}")
    return r["data"]


def posts(key, start):
    out = []
    for org in gql(key, "{ account { organizations { id } } }")["account"]["organizations"]:
        after = None
        while True:
            p = gql(key, """query($o: OrganizationId!, $s: DateTime!, $a: String){ posts(first: 100, after: $a,
                    input:{organizationId:$o, filter:{status:[scheduled, sending, sent, error], dueAt:{start:$s}}}) {
                    pageInfo { hasNextPage endCursor } edges { node { id dueAt status schedulingType text externalLink
                    channel { name service } error { message } assets { source } } } } }""",
                    {"o": org["id"], "s": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "a": after})["posts"]
            out += [e["node"] for e in p["edges"]]
            if not p["pageInfo"]["hasNextPage"]:
                break
            after = p["pageInfo"]["endCursor"]
    return out


def when(p):
    return dt.datetime.fromisoformat(p["dueAt"].replace("Z", "+00:00")).astimezone(PRAGUE)


def where(brand, p):
    return f"{brand} · {SERVICE.get(p['channel']['service'], p['channel']['service'])} ({p['channel']['name']})"


def short(text, n=120):
    text = (text or "").split("\n")[0]
    return text if len(text) <= n else text[:n - 1] + "…"


def message(brand, p):
    """Text for a post that is due, or None while an automatic post is still waiting to go out."""
    t = when(p).strftime("%H:%M")
    if p["schedulingType"] == "notification":
        video = next((a["source"] for a in p.get("assets") or [] if a.get("source")), "")
        return (f"📲 ZVEŘEJNI TEĎ – {where(brand, p)} {t}\nOtevři Buffer → Open in app, přidej trendový zvuk.\n"
                f"{video}\n\n{p['text'] or ''}").strip()
    if p["status"] == "sent":
        return f"✅ Vyšlo – {where(brand, p)} {t}\n{short(p['text'])}\n{p.get('externalLink') or ''}".strip()
    if p["status"] == "error":
        return f"❌ CHYBA – {where(brand, p)} {t}\n{short(p['text'])}\n{(p.get('error') or {}).get('message', '')}".strip()
    return None


def summary(found, day):
    lines = [f"☀️ Dnes {day.strftime('%d.%m.')} vyjde:"]
    for brand, p in sorted(found, key=lambda bp: bp[1]["dueAt"]):
        if when(p).date() == day and p["status"] == "scheduled":
            hand = " 📲 ručně" if p["schedulingType"] == "notification" else ""
            lines.append(f"{when(p).strftime('%H:%M')} {where(brand, p)}{hand} – {short(p['text'], 60)}")
    return "\n".join(lines) if len(lines) > 1 else lines[0] + " nic naplánovaného."


# channels that must never run empty (user, 2026-10-25: Printara TikTok went 3 days without posts)
WATCH = [("GARY", "instagram"), ("GARY", "youtube"), ("TALIA", "tiktok"), ("TALIA", "instagram"),
         ("PRINTARA", "tiktok"), ("PRINTARA", "instagram")]
# Pinterest queues hold < 2 days of pins (10 slots), so their runway comes from the plan files the fill jobs read
PLANS = {("TALIA", "pinterest"): "pinterest_plan.json", ("PRINTARA", "pinterest"): "printara_plan.json"}
RUNWAY = dt.timedelta(days=3)


def runway(found, now):
    """Warning lines for channels whose last planned post is less than RUNWAY away (or that have none)."""
    last = {}
    for brand, p in found:
        if p["status"] == "scheduled" and when(p) > now:
            k = (brand, p["channel"]["service"])
            last[k] = max(last.get(k, when(p)), when(p))
    for k, name in PLANS.items():
        path = STATE.parent / name
        if path.exists():
            due = [dt.datetime.fromisoformat(i["due"].replace("Z", "+00:00")) for i in
                   json.loads(path.read_text(encoding="utf-8"))]
            last[k] = max(due).astimezone(PRAGUE) if due else None
    rem = STATE.parent / "tg_reminders.json"
    if rem.exists():
        due = [dt.datetime.fromisoformat(r["at"].replace("Z", "+00:00")) for r in
               json.loads(rem.read_text(encoding="utf-8")) if r["id"].startswith("karusel")]
        last[("TALIA", "karusely")] = max(due).astimezone(PRAGUE) if due else None
    lines = []
    for k in WATCH + list(PLANS) + [("TALIA", "karusely")]:
        t = last.get(k)
        if t is None or t - now < RUNWAY:
            name = SERVICE.get(k[1], k[1])
            lines.append(f"⚠️ {k[0]} · {name}: " + (f"poslední post {t.strftime('%d.%m. %H:%M')}" if t else
                                                    "nic naplánováno") + " – doplň obsah!")
    return lines


def send(text, dry):
    if dry:
        print("---\n" + text)
        return
    data = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT"], "text": text[:4000],
                                   "disable_web_page_preview": "true"}).encode()
    urllib.request.urlopen("https://api.telegram.org/bot" + os.environ["TELEGRAM_TOKEN"] + "/sendMessage",
                           data=data, timeout=60)


def reminders(state, now, dry):
    """Manual-post reminders from cloud/tg_reminders.json ([{id, at (UTC ISO), html}], written by
    talia social/tools/talia_telegram.py). Each one is sent once when due; older than 6 h are dropped silently."""
    path = STATE.parent / "tg_reminders.json"
    if not path.exists():
        return
    sent = state.setdefault("reminders", {})
    for r in json.loads(path.read_text(encoding="utf-8")):
        at = dt.datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
        if r["id"] in sent or at > now:
            continue
        if now - at < dt.timedelta(hours=6):
            if dry:
                print("--- reminder")
                print(r["html"])
            else:
                data = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_CHAT"], "text": r["html"][:4000],
                                               "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
                urllib.request.urlopen("https://api.telegram.org/bot" + os.environ["TELEGRAM_TOKEN"] + "/sendMessage",
                                       data=data, timeout=60)
        sent[r["id"]] = r["at"]
    cutoff = (now - dt.timedelta(days=3)).isoformat()
    state["reminders"] = {k: v for k, v in sent.items() if v >= cutoff[:16]}


def tg_call(method, fields, files=()):
    """Telegram API with multipart upload of local files [(field name, Path)]."""
    b = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for name, path in files:
        body += (f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + b"\r\n"
    body += f"--{b}--\r\n".encode()
    req = urllib.request.Request("https://api.telegram.org/bot" + os.environ["TELEGRAM_TOKEN"] + "/" + method, data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    urllib.request.urlopen(req, timeout=300)


def carousel_packages(state, now, dry):
    """TikTok carousels she posts herself with a sound (user 5.11.2026): slides in full quality + tap-to-copy caption,
    sent once within 30 h before the slot (cron gaps can be hours long). cloud/tg_carousel_plan.json."""
    path = STATE.parent / "tg_carousel_plan.json"
    if not path.exists():
        return
    sent = state.setdefault("tg_carousels", {})
    chat = os.environ.get("TELEGRAM_CHAT", "")
    for c in json.loads(path.read_text(encoding="utf-8")):
        at = dt.datetime.fromisoformat(c["due"].replace("Z", "+00:00"))
        if c["id"] in sent or at <= now or at - now > dt.timedelta(hours=30):
            continue
        files = [STATE.parent.parent / "c" / n for n in c["images"]]
        if dry:
            print("--- package", c["id"], c["when"], len(files), "slides")
            continue
        tg_call("sendMessage", {"chat_id": chat, "parse_mode": "HTML", "text":
                f"📦 <b>Talia: carousel na TikTok</b> ({html.escape(c['id'])})\nZveřejnit: <b>{c['when']}</b> (přidej zvuk)\n"
                "Fotky v plné kvalitě jsou níže, popisek pod nimi zkopíruješ klepnutím."})
        for i in range(0, len(files), 10):
            chunk = files[i:i + 10]
            media = [{"type": "document", "media": f"attach://f{k}"} for k in range(len(chunk))]
            if len(chunk) == 1:
                tg_call("sendDocument", {"chat_id": chat}, [("document", chunk[0])])
            else:
                tg_call("sendMediaGroup", {"chat_id": chat, "media": json.dumps(media)},
                        [(f"f{k}", p) for k, p in enumerate(chunk)])
        tg_call("sendMessage", {"chat_id": chat, "parse_mode": "HTML", "text": f"<pre>{html.escape(c['caption'])[:3900]}</pre>"})
        sent[c["id"]] = c["due"]


def main(dry):
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    first_run = not state
    done = state.get("done", {})
    now = dt.datetime.now(dt.timezone.utc)
    found = [(b, p) for b, env in BRANDS.items() if os.environ.get(env)
             for p in posts(os.environ[env], now - dt.timedelta(days=2))]
    for brand, p in sorted(found, key=lambda bp: bp[1]["dueAt"]):
        if p["id"] in done or when(p) > now:
            continue
        text = message(brand, p)
        if text is None:
            continue
        if not first_run:  # first run only records what already happened, no flood of old posts
            send(text, dry)
        done[p["id"]] = p["dueAt"]
    reminders(state, now, dry)
    try:
        carousel_packages(state, now, dry)
    except Exception as e:  # never lose the post notifications because of a package
        send(f"❌ Balíček carouselu se neposlal: {e}", dry)
    today = now.astimezone(PRAGUE)
    if today.hour >= 8 and state.get("summary") != today.date().isoformat():
        warn = runway(found, now)
        send(summary(found, today.date()) + ("\n\n" + "\n".join(warn) if warn else ""), dry)
        state["summary"] = today.date().isoformat()
    cutoff = (now - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    state["done"] = {k: v for k, v in done.items() if v >= cutoff}
    if not dry:
        STATE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main("--dry" in sys.argv)
