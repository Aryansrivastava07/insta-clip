import json
import math
import re
from typing import List, Dict, Any, Optional
from database import db_get_user_reels, USE_PRISMA, get_sqlite_conn
from processor import generate_embedding

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)

def compute_keyword_match_score(text: str, query_terms: List[str]) -> float:
    """Computes a normalized keyword overlap score."""
    if not text or not query_terms:
        return 0.0
    text_lower = text.lower()
    matches = sum(1 for term in query_terms if term in text_lower)
    return min(1.0, matches / len(query_terms))

def search_reels(
    user_id: int,
    query: str,
    tag_filter: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Hybrid search combining:
    1. Vector Cosine Similarity (Natural language / semantic meaning)
    2. Keyword relevance (BM25 for SQLite, term matching for Prisma)
    """
    rows = db_get_user_reels(user_id, tag_filter)
    if not rows:
        return []

    # If query is empty, return latest reels
    if not query.strip():
        results = []
        for r in rows[:limit]:
            item = dict(r)
            if item.get("tags") and isinstance(item["tags"], str):
                try:
                    item["tags"] = json.loads(item["tags"])
                except Exception:
                    pass
            item.pop("embedding", None)
            item["score"] = 1.0
            results.append(item)
        return results

    query_terms = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 1]
    fts_scores = {}

    # SQLite FTS5 optimization if available
    if not USE_PRISMA and query_terms:
        try:
            conn = get_sqlite_conn()
            cursor = conn.cursor()
            fts_query = " ".join([f'"{w}"*' for w in query_terms])
            cursor.execute(
                """
                SELECT rowid, rank FROM reels_fts 
                WHERE user_id = ? AND reels_fts MATCH ? 
                ORDER BY rank LIMIT 50
                """,
                (user_id, fts_query)
            )
            for row in cursor.fetchall():
                rank = row["rank"]
                norm_score = max(0.0, min(1.0, 1.0 / (1.0 + abs(rank))))
                fts_scores[row["rowid"]] = norm_score
            conn.close()
        except Exception:
            pass

    # Compute Query Vector for Semantic Similarity
    query_vector = generate_embedding(query, gemini_api_key)

    scored_results = []
    for r in rows:
        row_id = r["id"]
        sem_score = 0.0
        
        # Parse stored vector
        raw_emb = r.get("embedding")
        if raw_emb:
            try:
                emb = json.loads(raw_emb) if isinstance(raw_emb, str) else raw_emb
                sem_score = cosine_similarity(query_vector, emb)
            except Exception:
                sem_score = 0.0

        if row_id in fts_scores:
            kw_score = fts_scores[row_id]
        else:
            combined_text = f"{r.get('creator_username', '')} {r.get('caption', '')} {r.get('summary', '')} {r.get('transcript', '')} {r.get('on_screen_text', '')} {r.get('tags', '')}"
            kw_score = compute_keyword_match_score(combined_text, query_terms)

        # Hybrid weighting: 65% Semantic, 35% Exact Keyword
        combined_score = (sem_score * 0.65) + (kw_score * 0.35)

        item = dict(r)
        if item.get("tags") and isinstance(item["tags"], str):
            try:
                item["tags"] = json.loads(item["tags"])
            except Exception:
                pass
        item.pop("embedding", None)
        item["score"] = round(combined_score, 4)
        item["semantic_score"] = round(sem_score, 4)
        item["keyword_score"] = round(kw_score, 4)

        scored_results.append(item)

    # Sort descending by hybrid score
    scored_results.sort(key=lambda x: x["score"], reverse=True)
    return scored_results[:limit]
