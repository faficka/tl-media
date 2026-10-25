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
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
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
