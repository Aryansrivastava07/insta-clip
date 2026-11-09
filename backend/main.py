import os
import json
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import (
    init_db,
    db_create_user,
    db_get_user_by_username,
    db_update_user_settings,
    db_save_reel,
    db_get_existing_reel_ids,
    db_delete_reel,
    db_get_user_tags
)
from auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, UserRegisterReq, UserLoginReq, UserSettingsReq
)
from ig_sync import fetch_inbox_reels, extract_shortcode_from_url
from processor import (
    extract_reel_metadata_and_video,
    analyze_reel_with_gemini,
    generate_embedding
)
from search import search_reels

# Initialize database schema / connect to Prisma
init_db()

app = FastAPI(title="InstaClip - AI Reel Knowledge Base", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# --- AUTH ROUTES ---

@app.post("/api/auth/register")
def register(req: UserRegisterReq):
    username = req.username.strip().lower()
    existing = db_get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    pw_hash = hash_password(req.password)
    try:
        user_id = db_create_user(username, pw_hash)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create user: {str(e)}")

    token = create_access_token(user_id, username)
    return {"token": token, "username": username, "user_id": user_id}

@app.post("/api/auth/login")
def login(req: UserLoginReq):
    username = req.username.strip().lower()
    user = db_get_user_by_username(username)

    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user["id"], user["username"])
    return {"token": token, "username": user["username"], "user_id": user["id"]}

@app.get("/api/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "has_ig_session": bool(user.get("ig_session_id")),
        "has_gemini_key": bool(user.get("gemini_api_key")),
        "ig_session_preview": user["ig_session_id"][:10] + "..." if user.get("ig_session_id") else "",
        "gemini_api_key_preview": user["gemini_api_key"][:8] + "..." if user.get("gemini_api_key") else "",
    }

@app.put("/api/auth/settings")
def update_settings(req: UserSettingsReq, user: dict = Depends(get_current_user)):
    ig_session = req.ig_session_id.strip() if req.ig_session_id else None
    gemini_key = req.gemini_api_key.strip() if req.gemini_api_key else None

    db_update_user_settings(user["id"], ig_session_id=ig_session, gemini_api_key=gemini_key)
    return {"status": "success", "message": "Settings updated"}

# --- REEL INDEXING & SYNC ROUTES ---

class ManualIndexReq(BaseModel):
    reel_url: str

def process_and_save_reel(user_id: int, reel_info: dict, gemini_key: Optional[str], session_id: Optional[str]) -> bool:
    """Helper to analyze media and insert reel into the database."""
    reel_id = reel_info["reel_id"]
    reel_url = reel_info["reel_url"]
    creator = reel_info.get("creator_username") or "unknown"
    caption = reel_info.get("caption") or ""
    thumbnail = reel_info.get("thumbnail_url")

    # Step 1: Download media & metadata via yt-dlp
    meta = extract_reel_metadata_and_video(reel_url, session_id=session_id)
    if meta.get("description"):
        caption = meta["description"]
    if meta.get("uploader") and creator == "unknown":
        creator = meta["uploader"]
    if meta.get("thumbnail") and not thumbnail:
        thumbnail = meta["thumbnail"]

    # Step 2: AI Deep Analysis (multimodal or text-based)
    if gemini_key or os.environ.get("GEMINI_API_KEY"):
        ai_data = analyze_reel_with_gemini(
            gemini_api_key=gemini_key,
            reel_url=reel_url,
            caption=caption,
            creator=creator,
            video_path=meta.get("video_path")
        )
    else:
        ai_data = {
            "summary": caption[:250] if caption else f"Instagram Reel from @{creator}",
            "transcript": "Connect your Gemini API key in Settings for automatic speech-to-text transcription.",
            "on_screen_text": "Connect your Gemini API key in Settings to extract text, ingredients, and notes.",
            "tags": ["reel", "instagram", creator.lower()]
        }

    # Step 3: Embeddings
    full_text = f"{creator} {caption} {ai_data['summary']} {ai_data['transcript']} {ai_data['on_screen_text']} {' '.join(ai_data['tags'])}"
    emb = generate_embedding(full_text, gemini_key)

    # Step 4: Persist in Prisma / SQLite
    return db_save_reel(
        user_id=user_id,
        reel_id=reel_id,
        reel_url=reel_url,
        creator_username=creator,
        caption=caption,
        summary=ai_data["summary"],
        transcript=ai_data["transcript"],
        on_screen_text=ai_data["on_screen_text"],
        tags=json.dumps(ai_data["tags"]),
        thumbnail_url=thumbnail,
        embedding=json.dumps(emb)
    )

@app.post("/api/reels/sync")
def sync_inbox(user: dict = Depends(get_current_user)):
    session_id = user.get("ig_session_id")
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="No Instagram session ID configured. Please add your dummy account's sessionid in Settings."
        )

    try:
        reels_in_inbox = fetch_inbox_reels(session_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing_ids = db_get_existing_reel_ids(user["id"])
    new_indexed = 0
    skipped = 0

    for item in reels_in_inbox:
        if item["reel_id"] in existing_ids:
            skipped += 1
            continue
        success = process_and_save_reel(
            user_id=user["id"],
            reel_info=item,
            gemini_key=user.get("gemini_api_key"),
            session_id=session_id
        )
        if success:
            new_indexed += 1

    return {
        "status": "success",
        "total_found_in_inbox": len(reels_in_inbox),
        "new_indexed": new_indexed,
        "already_indexed": skipped
    }

@app.post("/api/reels/index-manual")
def index_manual(req: ManualIndexReq, user: dict = Depends(get_current_user)):
    shortcode = extract_shortcode_from_url(req.reel_url)
    if not shortcode:
        raise HTTPException(status_code=400, detail="Invalid Instagram Reel URL. Expected format: https://www.instagram.com/reel/CODE/")

    reel_info = {
        "reel_id": shortcode,
        "reel_url": f"https://www.instagram.com/reel/{shortcode}/",
        "creator_username": None,
        "caption": "",
        "thumbnail_url": None
    }

    success = process_and_save_reel(
        user_id=user["id"],
        reel_info=reel_info,
        gemini_key=user.get("gemini_api_key"),
        session_id=user.get("ig_session_id")
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to process and index the Reel.")

    return {"status": "success", "message": f"Reel {shortcode} indexed successfully."}

@app.get("/api/reels")
def list_reels(
    q: str = Query("", description="Natural language search query"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user)
):
    results = search_reels(
        user_id=user["id"],
        query=q,
        tag_filter=tag,
        gemini_api_key=user.get("gemini_api_key"),
        limit=limit
    )
    return {"results": results, "total": len(results)}

@app.delete("/api/reels/{reel_id}")
def delete_reel(reel_id: str, user: dict = Depends(get_current_user)):
    deleted = db_delete_reel(user["id"], reel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Reel not found")
    return {"status": "success", "message": "Reel deleted"}

@app.get("/api/tags")
def get_user_tags(user: dict = Depends(get_current_user)):
    raw_tags = db_get_user_tags(user["id"])
    tag_counts = {}
    for t in raw_tags:
        clean = t.lower().strip()
        if clean:
            tag_counts[clean] = tag_counts.get(clean, 0) + 1

    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return {"tags": [{"tag": t, "count": c} for t, c in sorted_tags[:30]]}

# --- STATIC FRONTEND SERVING ---
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
def serve_home():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"message": "InstaClip API running. Frontend index.html not found."})
