"""
Asali.Life Instagram & Facebook Auto-Publisher
Reads schedule.json, publishes any pending posts whose time has passed.
Runs via GitHub Actions cron. Supports both video reels and image posts.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

TOKEN = os.environ["META_PAGE_ACCESS_TOKEN"]
IG_ID = os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
PAGE_ID = os.environ["META_PAGE_ID"]
REPO = "SalamAsali/ai-dreams-scheduler"

SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "schedule.json")


def load_schedule():
    with open(SCHEDULE_FILE, "r") as f:
        return json.load(f)


def save_schedule(schedule):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f, indent=2)


def api_post(url, params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def api_get(url):
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def get_media_url(post):
    """Get the public URL for the media file."""
    if "video_file_id" in post:
        return f"https://drive.google.com/uc?export=download&id={post['video_file_id']}"
    elif "video_file" in post:
        return f"https://raw.githubusercontent.com/{REPO}/main/videos/{post['video_file']}"
    elif "image_file" in post:
        return f"https://raw.githubusercontent.com/{REPO}/main/images/{post['image_file']}"
    return None


def publish_to_instagram(media_url, caption, media_type="REELS"):
    """Create container, wait for processing, publish."""
    print(f"  [IG] Creating container ({media_type})...")

    params = {"caption": caption, "access_token": TOKEN}
    if media_type == "REELS":
        params["media_type"] = "REELS"
        params["video_url"] = media_url
    else:
        params["image_url"] = media_url

    result = api_post(f"https://graph.facebook.com/v25.0/{IG_ID}/media", params)
    container_id = result["id"]
    print(f"  [IG] Container: {container_id}")

    for i in range(120):
        status = api_get(
            f"https://graph.facebook.com/v25.0/{container_id}"
            f"?fields=status_code&access_token={TOKEN}"
        )
        code = status.get("status_code", "")
        if code == "FINISHED":
            print(f"  [IG] Processing complete")
            break
        elif code == "ERROR":
            print(f"  [IG] ERROR: {status}")
            return None
        time.sleep(5)
    else:
        print(f"  [IG] Timeout waiting for processing")
        return None

    pub = api_post(
        f"https://graph.facebook.com/v25.0/{IG_ID}/media_publish",
        {"creation_id": container_id, "access_token": TOKEN},
    )
    media_id = pub["id"]

    verify = api_get(
        f"https://graph.facebook.com/v25.0/{media_id}"
        f"?fields=permalink&access_token={TOKEN}"
    )
    permalink = verify.get("permalink", "")
    print(f"  [IG] Published: {permalink}")
    return permalink


def publish_to_facebook(media_url, caption, media_type="REELS"):
    """Post to Facebook Page."""
    print(f"  [FB] Publishing...")
    if media_type == "REELS":
        result = api_post(
            f"https://graph.facebook.com/v25.0/{PAGE_ID}/videos",
            {"file_url": media_url, "description": caption, "access_token": TOKEN},
        )
    else:
        result = api_post(
            f"https://graph.facebook.com/v25.0/{PAGE_ID}/photos",
            {"url": media_url, "message": caption, "access_token": TOKEN},
        )
    fb_id = result.get("id", "")
    print(f"  [FB] Published: {fb_id}")
    return fb_id


def main():
    schedule = load_schedule()
    now = datetime.now(timezone.utc)
    published_count = 0

    for post in schedule:
        if post["status"] != "pending":
            continue

        publish_time = datetime.fromisoformat(post["publish_time"]).astimezone(
            timezone.utc
        )

        if now >= publish_time:
            print(f"\n=== Publishing: {post['speaker']} ===")
            media_url = get_media_url(post)
            if not media_url:
                print(f"  No media URL found, skipping")
                continue

            media_type = post.get("media_type", "REELS")
            ig_link = publish_to_instagram(media_url, post["caption"], media_type)
            fb_id = publish_to_facebook(media_url, post["caption"], media_type)

            if ig_link:
                post["status"] = "published"
                post["ig_permalink"] = ig_link
                post["fb_id"] = fb_id
                post["published_at"] = now.isoformat()
                published_count += 1
            else:
                post["status"] = "failed"
                print(f"  FAILED to publish {post['speaker']}")

    save_schedule(schedule)

    if published_count > 0:
        print(f"\nPublished {published_count} post(s)")
    else:
        print("No posts due right now")

    return published_count


if __name__ == "__main__":
    count = main()
    sys.exit(0)
