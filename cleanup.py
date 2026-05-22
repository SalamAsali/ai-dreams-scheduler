"""
One-time cleanup: delete bulk-published posts from IG, reset and reschedule at 3/day.
Also runs FB diagnostic to identify the 400 error.
"""
import json
import os
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
IG_ID = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
PAGE_ID = os.environ["META_PAGE_ID"]
SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "schedule.json")

BULK_PUBLISHED_IDS = [
    "ai-content-creation-speed", "ai-knowledge-gap", "ai-seo-revolution",
    "ai-agents-workforce", "ai-copywriting-dead", "ai-data-goldmine",
    "ai-social-media-algorithm", "ai-video-editing-revolution"
]


def api_delete(url):
    req = urllib.request.Request(url, method="DELETE")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def diagnose_facebook():
    """Run diagnostics on the FB Page connection."""
    print("\n=== Facebook Diagnostics ===")

    # 1. Check if PAGE_ID is valid
    print(f"  PAGE_ID: {PAGE_ID}")
    try:
        url = f"https://graph.facebook.com/v25.0/{PAGE_ID}?fields=id,name,access_token&access_token={TOKEN}"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req)
        page_info = json.loads(resp.read())
        print(f"  Page found: {page_info.get('name', 'unknown')} (ID: {page_info.get('id')})")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Page lookup FAILED: {e} — {body}")
        return

    # 2. Check token permissions
    try:
        url = f"https://graph.facebook.com/v25.0/me/permissions?access_token={TOKEN}"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req)
        perms = json.loads(resp.read())
        granted = [p['permission'] for p in perms.get('data', []) if p.get('status') == 'granted']
        declined = [p['permission'] for p in perms.get('data', []) if p.get('status') == 'declined']
        print(f"  Granted permissions: {', '.join(granted)}")
        if declined:
            print(f"  DECLINED permissions: {', '.join(declined)}")

        needed = ['pages_manage_posts', 'pages_read_engagement', 'pages_show_list']
        missing = [p for p in needed if p not in granted]
        if missing:
            print(f"  MISSING required permissions: {', '.join(missing)}")
        else:
            print(f"  All required FB permissions present")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Permission check FAILED: {e} — {body}")

    # 3. Check token type (user vs page token)
    try:
        url = f"https://graph.facebook.com/v25.0/me?fields=id,name&access_token={TOKEN}"
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req)
        me = json.loads(resp.read())
        print(f"  Token belongs to: {me.get('name', 'unknown')} (ID: {me.get('id')})")
        if me.get('id') == PAGE_ID:
            print(f"  Token type: PAGE token (correct for page posting)")
        else:
            print(f"  Token type: USER token — this may be the issue!")
            print(f"  For posting as a Page, you need a Page Access Token, not a User token.")
            print(f"  Get one from: Graph API Explorer > select your Page > generate token")

            # Try to get page token from user token
            print(f"  Attempting to fetch page token from user token...")
            url2 = f"https://graph.facebook.com/v25.0/me/accounts?access_token={TOKEN}"
            req2 = urllib.request.Request(url2)
            resp2 = urllib.request.urlopen(req2)
            accounts = json.loads(resp2.read())
            for acct in accounts.get('data', []):
                print(f"    Page: {acct.get('name')} (ID: {acct.get('id')})")
                if acct.get('id') == PAGE_ID:
                    print(f"    ^ This matches PAGE_ID! The page token for this page should be used.")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Token info FAILED: {e} — {body}")

    # 4. Try a minimal FB post to see the exact error
    print(f"\n  Attempting test FB text post...")
    try:
        data = urllib.parse.urlencode({
            "message": "Test post - will be deleted",
            "access_token": TOKEN
        }).encode()
        req = urllib.request.Request(
            f"https://graph.facebook.com/v25.0/{PAGE_ID}/feed",
            data=data, method="POST"
        )
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        test_id = result.get("id")
        print(f"  Test post SUCCEEDED: {test_id}")
        # Delete it immediately
        try:
            api_delete(f"https://graph.facebook.com/v25.0/{test_id}?access_token={TOKEN}")
            print(f"  Test post deleted")
        except:
            print(f"  Warning: couldn't delete test post {test_id}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  Test post FAILED: {e} — {body}")
        print(f"  This is the root cause of the FB 400 errors.")


def main():
    with open(SCHEDULE_FILE) as f:
        schedule = json.load(f)

    # Fetch recent IG media
    print("Fetching recent IG media...")
    try:
        url = (
            f"https://graph.facebook.com/v25.0/{IG_ID}/media"
            f"?fields=id,permalink,timestamp&limit=20&access_token={TOKEN}"
        )
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req)
        media_list = json.loads(resp.read()).get("data", [])
        print(f"  Found {len(media_list)} recent posts")
    except Exception as e:
        print(f"  Failed to fetch media: {e}")
        media_list = []

    permalink_to_id = {m.get("permalink", ""): m["id"] for m in media_list}

    # Delete bulk-published posts
    deleted_count = 0
    for post in schedule:
        if post["id"] not in BULK_PUBLISHED_IDS:
            continue

        print(f"\n=== Cleaning up: {post['speaker']} ===")

        ig_link = post.get("ig_permalink", "")
        ig_media_id = permalink_to_id.get(ig_link)
        if ig_media_id:
            try:
                result = api_delete(
                    f"https://graph.facebook.com/v25.0/{ig_media_id}?access_token={TOKEN}"
                )
                print(f"  [IG] Deleted {ig_media_id}: {result}")
            except Exception as e:
                print(f"  [IG] Delete failed: {e}")
        else:
            print(f"  [IG] Could not find media ID for {ig_link}")

        # No FB posts to delete (they all failed)

        post["status"] = "pending"
        for key in ["ig_permalink", "fb_id", "published_at"]:
            post.pop(key, None)
        deleted_count += 1

    # Reschedule all pending posts at 3/day
    print("\n=== Rescheduling posts ===")
    edt = timezone(timedelta(hours=-4))
    tomorrow = datetime(2026, 5, 23, 0, 0, 0, tzinfo=edt)
    time_slots = [
        timedelta(hours=11),
        timedelta(hours=17),
        timedelta(hours=21),
    ]

    pending = [p for p in schedule if p["status"] == "pending"]
    slot_idx = 0
    day_offset = 0

    for post in pending:
        new_time = tomorrow + timedelta(days=day_offset) + time_slots[slot_idx]
        post["publish_time"] = new_time.isoformat()
        print(f"  {post['speaker']:25s} -> {new_time.strftime('%Y-%m-%d %I:%M %p EDT')}")
        slot_idx += 1
        if slot_idx >= 3:
            slot_idx = 0
            day_offset += 1

    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f, indent=2)

    print(f"\nDone: deleted {deleted_count} posts, rescheduled {len(pending)} pending posts")

    # Run FB diagnostics
    diagnose_facebook()


if __name__ == "__main__":
    main()
