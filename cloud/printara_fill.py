"""Hourly GitHub Action: top up Printara's Buffer queue (Pinterest printaraco) from cloud/printara_plan.json.

Same logic as talia_fill.py, for Printara's own Buffer organization (secret BUFFER_KEY_PRINTARA).
Buffer's free plan holds max 10 scheduled posts per channel. Every run creates the next planned posts that are
not in Buffer yet (matched by channel + due minute) while the channel has free slots. Past items are skipped.
The plan is written by ASTRA/Printara/tools/build_pins_gifts.py (gift-guide pins, one unique photo per pin);
a planned post deleted by hand in Buffer gets re-created - remove it from the plan instead (--plan-only, then push).
Pinterest items carry "board" = board name, resolved here; if that board does not exist (yet), "fallback_board" is used.
Usage: BUFFER_KEY_PRINTARA=... python3 cloud/printara_fill.py cloud/printara_plan.json [--dry]
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ORG = "6acfb6d1e37cd4ba31dfd7c4"
LIMIT = 10


def gql(query, variables=None):
    req = urllib.request.Request("https://api.buffer.com",
                                 data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["BUFFER_KEY_PRINTARA"],
                                          "Content-Type": "application/json", "User-Agent": "printara/1.0"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        return {"errors": [{"message": f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"}]}


def existing(start):
    nodes, after = [], None
    while True:
        r = gql("""query($o: OrganizationId!, $s: DateTime!, $a: String){ posts(first: 100, after: $a, input:{organizationId:$o,
                   filter:{status:[scheduled, sending, sent, error], dueAt:{start:$s}}}) {
                   pageInfo { hasNextPage endCursor } edges { node { channelId dueAt status } } } }""",
                {"o": ORG, "s": start, "a": after})
        if "errors" in r:
            sys.exit(f"Buffer error: {r['errors']}")
        nodes += [e["node"] for e in r["data"]["posts"]["edges"]]
        if not r["data"]["posts"]["pageInfo"]["hasNextPage"]:
            return nodes
        after = r["data"]["posts"]["pageInfo"]["endCursor"]


def main(plan_paths, dry=False):
    plan = sorted((it for p in plan_paths for it in json.loads(Path(p).read_text(encoding="utf-8"))),
                  key=lambda it: it["due"])
    r = gql("""query($o: OrganizationId!){ channels(input:{organizationId:$o}) { id service isDisconnected
               metadata { ... on PinterestMetadata { boards { serviceId name } } } } }""", {"o": ORG})
    if "errors" in r:
        sys.exit(f"Buffer error: {r['errors']}")
    chans = {c["service"]: c["id"] for c in r["data"]["channels"] if not c["isDisconnected"]}
    boards = {b["name"]: b["serviceId"] for c in r["data"]["channels"] for b in (c.get("metadata") or {}).get("boards", [])}
    now = dt.datetime.now(dt.timezone.utc)
    soon = (now + dt.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M")
    have = existing((now - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    done = {(n["channelId"], n["dueAt"][:16]) for n in have}
    queued = {cid: sum(1 for n in have if n["channelId"] == cid and n["status"] == "scheduled") for cid in chans.values()}
    for it in plan:
        cid = chans.get(it["service"])
        if not cid or it["due"][:16] < soon or (cid, it["due"][:16]) in done or queued[cid] >= LIMIT:
            continue
        post = {**it["post"], "channelId": cid}
        if "board" in it:
            board = boards.get(it["board"]) or boards[it["fallback_board"]]
            post["metadata"] = {"pinterest": {**post["metadata"]["pinterest"], "boardServiceId": board}}
        if dry:
            queued[cid] += 1
            print("DRY ", it["service"], it["due"], it["label"], post["metadata"]["pinterest"].get("boardServiceId"))
            continue
        r = gql("""mutation($i: CreatePostInput!){ createPost(input:$i){ ... on PostActionSuccess { post { id } }
                   ... on MutationError { message } } }""", {"i": post})
        res = (r.get("data") or {}).get("createPost") or r
        if "post" in res:
            queued[cid] += 1
            print("OK  ", it["service"], it["label"])
        else:
            print("FAIL", it["service"], it["label"], res)
            if "limit" in str(res).lower():
                queued[cid] = LIMIT
    print("queue:", {s: queued[c] for s, c in chans.items()})


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if a != "--dry"], "--dry" in sys.argv)
