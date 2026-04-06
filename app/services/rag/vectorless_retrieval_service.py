"""
Vectorless retrieval service (lexical search over persisted chunks).
"""

from __future__ import annotations

from typing import Any, Optional
import re
import time
import json

from app.core.config import settings
from app.repositories.file_chunk_repository import FileChunkRepository
from app.services.rag.utils.file_utils import remove_accents


class VectorlessRetrievalService:
    def __init__(self):
        self._chunk_repo: Optional[FileChunkRepository] = None
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._vi_stopwords: set[str] = {
            "va", "la", "cua", "cho", "voi", "mot", "nhung", "cac", "trong", "tren", "duoc", "khong",
            "toi", "ban", "anh", "chi", "em", "ve", "tu", "den", "khi", "neu", "thi", "nay", "kia",
            "do", "day", "da", "dang", "se", "co", "the", "o", "tai", "ma", "nhu", "gi", "nao",
        }
        extra_stopwords = [
            self._normalize_text(x)
            for x in (settings.VECTORLESS_EXTRA_STOPWORDS or "").split(",")
            if self._normalize_text(x)
        ]
        self._vi_stopwords.update(extra_stopwords)

    @property
    def chunk_repo(self) -> FileChunkRepository:
        if self._chunk_repo is None:
            self._chunk_repo = FileChunkRepository()
        return self._chunk_repo

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
        user_role: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        top_k = max(1, int(top_k or settings.VECTORLESS_TOP_K))
        min_score = float(settings.VECTORLESS_MIN_SCORE if min_score is None else min_score)

        q_norm = self._normalize_text(query or "")
        terms = [t for t in self._tokenize(q_norm) if len(t) > 1 and t not in self._vi_stopwords]

        cache_key = self._make_cache_key(
            query=q_norm,
            top_k=top_k,
            min_score=min_score,
            metadata_filter=metadata_filter,
            user_role=user_role,
        )
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and now - cached[0] <= settings.VECTORLESS_CACHE_TTL_SECONDS:
            self._cache_hits += 1
            return cached[1]
        self._cache_misses += 1

        docs = await self.chunk_repo.find_many(
            query={},
            skip=0,
            limit=max(100, int(settings.VECTORLESS_MAX_SCAN_DOCS)),
        )

        if user_role and user_role != "admin":
            docs = [d for d in docs if self._allow_role(d.get("metadata") or {}, user_role)]

        if metadata_filter:
            docs = [d for d in docs if self._match_metadata(d.get("metadata") or {}, metadata_filter)]

        rescored: list[tuple[float, dict[str, Any]]] = []
        for d in docs:
            text_raw = d.get("text") or ""
            text_norm = self._normalize_text(text_raw)
            if not text_norm:
                continue

            phrase_hits = text_norm.count(q_norm) if q_norm else 0
            phrase_score = phrase_hits * 6.0

            token_score = 0.0
            matched_terms = 0
            for t in terms:
                freq = text_norm.count(t)
                if freq <= 0:
                    continue
                matched_terms += 1
                weight = 1.0
                if len(t) >= 6:
                    weight = 1.5
                if len(t) >= 9:
                    weight = 2.0
                token_score += freq * weight

            section = self._normalize_text(str(d.get("section_path") or ""))
            section_boost = 2.0 if section and any(t in section for t in terms) else 0.0

            m = d.get("metadata") or {}
            hoc_ky = str(m.get("hoc_ky") or "")
            nam_hoc = str(m.get("nam_hoc") or "")
            recency_boost = (0.1 if hoc_ky else 0.0) + (0.2 if nam_hoc else 0.0)

            final_score = phrase_score + token_score + section_boost + recency_boost
            if final_score < min_score:
                continue

            explain = {
                "phrase_hits": phrase_hits,
                "phrase_score": round(phrase_score, 4),
                "matched_terms": matched_terms,
                "token_score": round(token_score, 4),
                "section_boost": round(section_boost, 4),
                "recency_boost": round(recency_boost, 4),
                "final_score": round(final_score, 4),
            }

            d_copy = dict(d)
            d_copy["_retrieval_score"] = round(final_score, 4)
            d_copy["_retrieval_explain"] = explain
            rescored.append((final_score, d_copy))

        rescored.sort(key=lambda x: x[0], reverse=True)
        result = [d for _, d in rescored[:top_k]]

        self._cache[cache_key] = (now, result)
        self._evict_cache_if_needed()
        return result

    @staticmethod
    def _make_cache_key(
        query: str,
        top_k: int,
        min_score: float,
        metadata_filter: Optional[dict[str, Any]],
        user_role: Optional[str],
    ) -> str:
        payload = {
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
            "metadata_filter": metadata_filter or {},
            "user_role": user_role or "",
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def _evict_cache_if_needed(self) -> None:
        max_keys = max(10, int(settings.VECTORLESS_CACHE_MAX_KEYS))
        if len(self._cache) <= max_keys:
            return

        # remove oldest entries first
        oldest_keys = sorted(self._cache.items(), key=lambda kv: kv[1][0])[: len(self._cache) - max_keys]
        for k, _ in oldest_keys:
            self._cache.pop(k, None)

    @staticmethod
    def _allow_role(metadata: dict[str, Any], user_role: str) -> bool:
        access = metadata.get("access_scope")
        if access is None:
            return True
        if isinstance(access, str):
            access_values = [access]
        elif isinstance(access, list):
            access_values = [str(x) for x in access]
        else:
            return True
        return user_role in access_values

    def get_cache_stats(self) -> dict[str, Any]:
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total) if total > 0 else 0.0
        return {
            "cache_size": len(self._cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": round(hit_rate, 4),
            "ttl_seconds": int(settings.VECTORLESS_CACHE_TTL_SECONDS),
            "max_keys": int(settings.VECTORLESS_CACHE_MAX_KEYS),
        }


    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        text = remove_accents(text.lower())
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        if not text:
            return []
        return [tok for tok in text.split(" ") if tok]

    @staticmethod
    def _match_metadata(metadata: dict[str, Any], filter_data: dict[str, Any]) -> bool:
        for k, v in filter_data.items():
            if v is None:
                continue
            current = metadata.get(k)
            if isinstance(v, list):
                if current not in v:
                    return False
            else:
                if current != v:
                    return False
        return True


_vectorless_retrieval_service_instance: Optional[VectorlessRetrievalService] = None


def get_vectorless_retrieval_service() -> VectorlessRetrievalService:
    global _vectorless_retrieval_service_instance
    if _vectorless_retrieval_service_instance is None:
        _vectorless_retrieval_service_instance = VectorlessRetrievalService()
    return _vectorless_retrieval_service_instance

