import os
import json
import re
import math
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
import yt_dlp
from google import genai
from google.genai import types

TEMP_DIR = Path(__file__).resolve().parent.parent / "data" / "temp_media"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

def extract_reel_metadata_and_video(reel_url: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Attempts to download reel media and metadata via yt-dlp.
    Falls back gracefully if download is blocked or unavailable.
    """
    timestamp = int(time.time() * 1000)
    out_template = str(TEMP_DIR / f"reel_{timestamp}.%(ext)s")

    ydl_opts = {
        'format': 'mp4/best[ext=mp4]/best',
        'outtmpl': out_template,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 15,
        'noplaylist': True,
    }

    if session_id:
        clean_cookie = session_id.strip()
        if not clean_cookie.startswith("sessionid="):
            cookie_val = clean_cookie
        else:
            cookie_val = clean_cookie.replace("sessionid=", "").rstrip(";")
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Cookie': f'sessionid={cookie_val};'
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(reel_url, download=True)
            video_file = ydl.prepare_filename(info)
            # Ensure mp4 extension check
            if not os.path.exists(video_file):
                # Search matching prefix in temp dir
                candidates = list(TEMP_DIR.glob(f"reel_{timestamp}.*"))
                video_file = str(candidates[0]) if candidates else None

            return {
                "success": True,
                "video_path": video_file if video_file and os.path.exists(video_file) else None,
                "title": info.get("title", ""),
                "description": info.get("description", "") or info.get("caption", ""),
                "uploader": info.get("uploader", "") or info.get("channel", ""),
                "thumbnail": info.get("thumbnail", ""),
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "video_path": None,
            "title": "",
            "description": "",
            "uploader": "",
            "thumbnail": "",
        }

def analyze_reel_with_gemini(
    gemini_api_key: Optional[str],
    reel_url: str,
    caption: str,
    creator: str,
    video_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Uses Google Gemini Flash to deeply analyze the reel:
    - Transcribes audio/speech
    - Extracts on-screen text & key takeaways
    - Generates 2-3 sentence summary & topics
    """
    api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No Gemini API key provided")
    client = genai.Client(api_key=api_key)
    uploaded_file = None

    prompt = f"""
You are an expert AI video archivist and research assistant.
Analyze this Instagram Reel (URL: {reel_url}, Creator: @{creator or 'unknown'}).
Original caption/notes: "{caption or 'None provided'}".

Return a valid JSON object strictly matching this schema:
{{
  "summary": "2 to 3 concise, highly informative sentences explaining what this reel is about and its core takeaways or advice.",
  "transcript": "Accurate transcription of the spoken dialogue, voiceover, or lyrics in the video.",
  "on_screen_text": "Key bullet points, instructions, ingredients, code, stats, or text displayed on screen.",
  "tags": ["topic1", "topic2", "topic3", "topic4"]
}}
Only return raw JSON, no markdown formatting or extra commentary.
"""

    try:
        # If we have a video file, upload to Gemini for true multimodal audio + visual inspection
        if video_path and os.path.exists(video_path):
            try:
                uploaded_file = client.files.upload(file=video_path)
                # Wait briefly if state is processing
                for _ in range(10):
                    file_info = client.files.get(name=uploaded_file.name)
                    if file_info.state == "ACTIVE":
                        break
                    time.sleep(1)

                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[uploaded_file, prompt]
                )
            except Exception:
                # Fallback to text prompt if video upload fails
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[prompt]
                )
        else:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt]
            )

        text = response.text.strip()
        # Clean potential markdown fences ```json ... ```
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        data = json.loads(text)
        return {
            "summary": data.get("summary", ""),
            "transcript": data.get("transcript", ""),
            "on_screen_text": data.get("on_screen_text", ""),
            "tags": data.get("tags", [])
        }

    except Exception as e:
        # Fallback heuristic if API call fails
        tags = [t.strip("#").lower() for t in re.findall(r"#\w+", caption)]
        return {
            "summary": caption[:200] if caption else f"Reel from @{creator}",
            "transcript": "Transcript unavailable (AI processing error: " + str(e) + ")",
            "on_screen_text": "On-screen text unavailable",
            "tags": tags[:5]
        }
    finally:
        # Cleanup uploaded remote file from Gemini
        if uploaded_file:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass
        # Cleanup local temp video
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass

def generate_embedding(text: str, gemini_api_key: Optional[str] = None) -> List[float]:
    """
    Generates semantic vector embeddings using Gemini's text-embedding model,
    or a normalized hashed n-gram fallback if no key is provided.
    """
    api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            client = genai.Client(api_key=api_key)
            result = client.models.embed_content(
                model="text-embedding-004",
                contents=text[:2000]
            )
            # result.embeddings is a list of ContentEmbedding
            if hasattr(result, "embeddings") and result.embeddings:
                return result.embeddings[0].values
        except Exception:
            pass

    # Lightweight local fallback embedding (128-dim normalized character n-gram hash)
    dim = 128
    vec = [0.0] * dim
    words = re.findall(r"\w+", text.lower())
    for w in words:
        idx = hash(w) % dim
        vec[idx] += 1.0

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec
