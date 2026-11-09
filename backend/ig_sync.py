import re
import requests
from typing import List, Dict, Any, Optional

IG_INBOX_URL = "https://www.instagram.com/api/v1/direct_v2/inbox/?persistentBadging=true&folder=&limit=20&thread_message_limit=20"
REEL_REGEX = re.compile(r"instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)")

def extract_shortcode_from_url(url: str) -> Optional[str]:
    match = REEL_REGEX.search(url)
    if match:
        return match.group(1)
    return None

def fetch_inbox_reels(session_id: str) -> List[Dict[str, Any]]:
    """
    Connects to Instagram Web DM inbox using the dummy account's sessionid cookie.
    Extracts all shared Reels across recent conversation threads.
    """
    clean_cookie = session_id.strip()
    if not clean_cookie.startswith("sessionid="):
        cookie_header = f"sessionid={clean_cookie};"
    else:
        cookie_header = clean_cookie

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": cookie_header,
        "Referer": "https://www.instagram.com/direct/inbox/",
    }

    try:
        response = requests.get(IG_INBOX_URL, headers=headers, timeout=15)
        if response.status_code == 401 or response.status_code == 403:
            raise Exception("Invalid or expired Instagram session ID. Please refresh your sessionid cookie.")
        if response.status_code != 200:
            raise Exception(f"Instagram responded with status code {response.status_code}")

        data = response.json()
        inbox = data.get("inbox", {})
        threads = inbox.get("threads", [])
        
        found_reels = []
        seen_codes = set()

        for thread in threads:
            for item in thread.get("items", []):
                item_type = item.get("item_type")
                shortcode = None
                creator = None
                caption = ""
                thumb = None

                # 1. Instagram Clip / Reel share
                if item_type == "clip":
                    clip_obj = item.get("clip", {}).get("clip", {})
                    shortcode = clip_obj.get("code")
                    creator = clip_obj.get("user", {}).get("username")
                    cap_dict = clip_obj.get("caption") or {}
                    caption = cap_dict.get("text", "")
                    image_versions = clip_obj.get("image_versions2", {}).get("candidates", [])
                    if image_versions:
                        thumb = image_versions[0].get("url")

                # 2. Instagram Media share (posts / reels)
                elif item_type == "media_share":
                    media = item.get("media_share", {})
                    shortcode = media.get("code")
                    creator = media.get("user", {}).get("username")
                    cap_dict = media.get("caption") or {}
                    caption = cap_dict.get("text", "")
                    image_versions = media.get("image_versions2", {}).get("candidates", [])
                    if image_versions:
                        thumb = image_versions[0].get("url")

                # 3. Direct link shared in message text
                elif item_type in ("link", "text"):
                    text_content = item.get("text") or item.get("link", {}).get("text") or item.get("link", {}).get("link_context", {}).get("link_url", "")
                    matched = extract_shortcode_from_url(text_content)
                    if matched:
                        shortcode = matched

                if shortcode and shortcode not in seen_codes:
                    seen_codes.add(shortcode)
                    found_reels.append({
                        "reel_id": shortcode,
                        "reel_url": f"https://www.instagram.com/reel/{shortcode}/",
                        "creator_username": creator,
                        "caption": caption,
                        "thumbnail_url": thumb
                    })

        return found_reels

    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to reach Instagram: {str(e)}")
