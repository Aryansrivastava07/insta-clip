import os
import json
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Set

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "instaclip.db"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PRISMA = bool(
    DATABASE_URL and (
        DATABASE_URL.startswith("postgres://") or
        DATABASE_URL.startswith("postgresql://") or
        DATABASE_URL.startswith("prisma+postgres://")
    )
)

prisma_client = None

def get_prisma():
    global prisma_client
    if prisma_client is None:
        from prisma import Prisma
        prisma_client = Prisma()
    if not prisma_client.is_connected():
        prisma_client.connect()
    return prisma_client

def init_db():
    """Initializes SQLite if not using Prisma, or connects to Prisma."""
    if USE_PRISMA:
        print("[DB] Using Prisma Cloud Database:", DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "configured")
        get_prisma()
        return

    # Fallback to SQLite
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        ig_session_id TEXT,
        gemini_api_key TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        reel_id TEXT NOT NULL,
        reel_url TEXT NOT NULL,
        creator_username TEXT,
        caption TEXT,
        summary TEXT,
        transcript TEXT,
        on_screen_text TEXT,
        tags TEXT,
        thumbnail_url TEXT,
        embedding TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id),
        UNIQUE(user_id, reel_id)
    );
    """)

    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS reels_fts USING fts5(
        reel_id UNINDEXED,
        user_id UNINDEXED,
        creator_username,
        caption,
        summary,
        transcript,
        on_screen_text,
        tags,
        content='reels',
        content_rowid='id'
    );
    """)

    conn.commit()
    conn.close()

def get_sqlite_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- UNIFIED REPOSITORY OPERATIONS ---

def db_create_user(username: str, password_hash: str) -> int:
    if USE_PRISMA:
        db = get_prisma()
        user = db.user.create(data={
            "username": username,
            "password_hash": password_hash
        })
        return user.id
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id

def db_get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    if USE_PRISMA:
        db = get_prisma()
        user = db.user.find_unique(where={"username": username})
        if not user:
            return None
        return {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
            "ig_session_id": user.ig_session_id,
            "gemini_api_key": user.gemini_api_key,
            "created_at": str(user.created_at)
        }
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

def db_get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    if USE_PRISMA:
        db = get_prisma()
        user = db.user.find_unique(where={"id": user_id})
        if not user:
            return None
        return {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
            "ig_session_id": user.ig_session_id,
            "gemini_api_key": user.gemini_api_key,
            "created_at": str(user.created_at)
        }
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

def db_update_user_settings(user_id: int, ig_session_id: Optional[str] = None, gemini_api_key: Optional[str] = None):
    if USE_PRISMA:
        db = get_prisma()
        data = {}
        if ig_session_id is not None:
            data["ig_session_id"] = ig_session_id
        if gemini_api_key is not None:
            data["gemini_api_key"] = gemini_api_key
        if data:
            db.user.update(where={"id": user_id}, data=data)
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        updates = []
        params = []
        if ig_session_id is not None:
            updates.append("ig_session_id = ?")
            params.append(ig_session_id)
        if gemini_api_key is not None:
            updates.append("gemini_api_key = ?")
            params.append(gemini_api_key)
        if updates:
            params.append(user_id)
            cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))
            conn.commit()
        conn.close()

def db_get_existing_reel_ids(user_id: int) -> Set[str]:
    if USE_PRISMA:
        db = get_prisma()
        reels = db.reel.find_many(where={"user_id": user_id})
        return {r.reel_id for r in reels}
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT reel_id FROM reels WHERE user_id = ?", (user_id,))
        ids = {row["reel_id"] for row in cursor.fetchall()}
        conn.close()
        return ids

def db_save_reel(
    user_id: int,
    reel_id: str,
    reel_url: str,
    creator_username: Optional[str],
    caption: str,
    summary: str,
    transcript: str,
    on_screen_text: str,
    tags: str,
    thumbnail_url: Optional[str],
    embedding: str
) -> bool:
    if USE_PRISMA:
        db = get_prisma()
        try:
            db.reel.upsert(
                where={"user_id_reel_id": {"user_id": user_id, "reel_id": reel_id}},
                data={
                    "create": {
                        "user_id": user_id,
                        "reel_id": reel_id,
                        "reel_url": reel_url,
                        "creator_username": creator_username,
                        "caption": caption,
                        "summary": summary,
                        "transcript": transcript,
                        "on_screen_text": on_screen_text,
                        "tags": tags,
                        "thumbnail_url": thumbnail_url,
                        "embedding": embedding,
                    },
                    "update": {
                        "summary": summary,
                        "transcript": transcript,
                        "on_screen_text": on_screen_text,
                        "tags": tags,
                        "thumbnail_url": thumbnail_url,
                        "embedding": embedding,
                    }
                }
            )
            return True
        except Exception as e:
            print(f"[Prisma] Error upserting reel: {e}")
            return False
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("""
            INSERT INTO reels (
                user_id, reel_id, reel_url, creator_username, caption,
                summary, transcript, on_screen_text, tags, thumbnail_url, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, reel_id) DO UPDATE SET
                summary=excluded.summary,
                transcript=excluded.transcript,
                on_screen_text=excluded.on_screen_text,
                tags=excluded.tags,
                thumbnail_url=COALESCE(excluded.thumbnail_url, reels.thumbnail_url),
                embedding=excluded.embedding
            """, (
                user_id, reel_id, reel_url, creator_username, caption,
                summary, transcript, on_screen_text, tags, thumbnail_url, embedding
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"[SQLite] Error saving reel: {e}")
            return False
        finally:
            conn.close()

def db_get_user_reels(user_id: int, tag_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    if USE_PRISMA:
        db = get_prisma()
        where = {"user_id": user_id}
        if tag_filter:
            where["tags"] = {"contains": tag_filter}
        reels = db.reel.find_many(where=where, order={"created_at": "desc"})
        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "reel_id": r.reel_id,
                "reel_url": r.reel_url,
                "creator_username": r.creator_username,
                "caption": r.caption,
                "summary": r.summary,
                "transcript": r.transcript,
                "on_screen_text": r.on_screen_text,
                "tags": r.tags,
                "thumbnail_url": r.thumbnail_url,
                "embedding": r.embedding,
                "created_at": str(r.created_at)
            }
            for r in reels
        ]
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        if tag_filter:
            cursor.execute(
                "SELECT * FROM reels WHERE user_id = ? AND tags LIKE ? ORDER BY created_at DESC",
                (user_id, f"%{tag_filter}%")
            )
        else:
            cursor.execute(
                "SELECT * FROM reels WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

def db_delete_reel(user_id: int, reel_id: str) -> bool:
    if USE_PRISMA:
        db = get_prisma()
        res = db.reel.delete_many(where={"user_id": user_id, "reel_id": reel_id})
        return res > 0
    else:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reels WHERE user_id = ? AND reel_id = ?", (user_id, reel_id))
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted

def db_get_user_tags(user_id: int) -> List[str]:
    reels = db_get_user_reels(user_id)
    all_tags = []
    for r in reels:
        raw = r.get("tags")
        if raw:
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list):
                    all_tags.extend(parsed)
            except Exception:
                pass
    return all_tags
