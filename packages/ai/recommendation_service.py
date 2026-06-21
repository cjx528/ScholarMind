"""Recommendation service.

@author ScholarMind Team
"""

from __future__ import annotations

from packages.domain.math_utils import cosine_similarity as _cosine_sim
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    """计算向量集合的质心（自动过滤维度不一致的向量）"""
    if not vectors:
        return []
    dim = len(vectors[0])
    valid = [v for v in vectors if len(v) == dim]
    if not valid:
        return []
    result = [0.0] * dim
    for v in valid:
        for i in range(dim):
            result[i] += v[i]
    n = len(valid)
    return [x / n for x in result]


class RecommendationService:
    """基于阅读历史 embedding 的个性化推荐"""

    def get_user_profile(self) -> list[float]:
        """从已读论文（skimmed/deep_read）的 embedding 计算兴趣向量"""
        with session_scope() as session:
            repo = PaperRepository(session)
            read_papers = repo.list_by_read_status_with_embedding(
                statuses=["skimmed", "deep_read"], limit=200
            )
            vectors = [list(p.embedding) for p in read_papers if p.embedding]
        if not vectors:
            return []
        return _mean_vector(vectors)

    def recommend(self, top_k: int = 10) -> list[dict]:
        """推荐与用户兴趣最匹配的未读论文"""
        profile = self.get_user_profile()
        if not profile:
            return []

        # 在 session 内提取所有需要的数据
        with session_scope() as session:
            repo = PaperRepository(session)
            unread = repo.list_unread_with_embedding(limit=200)
            candidates = []
            for p in unread:
                if not p.embedding:
                    continue
                meta = p.metadata_json or {}
                candidates.append(
                    {
                        "embedding": list(p.embedding),
                        "id": str(p.id),
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "abstract": (p.abstract or "")[:300],
                        "publication_date": (
                            str(p.publication_date) if p.publication_date else None
                        ),
                        "keywords": meta.get("keywords", []),
                        "categories": meta.get("categories", []),
                        "title_zh": meta.get("title_zh", ""),
                    }
                )

        profile_dim = len(profile)
        scored: list[tuple[float, dict]] = []
        for c in candidates:
            emb = c.pop("embedding")
            if len(emb) != profile_dim:
                continue
            sim = _cosine_sim(profile, emb)
            c["similarity"] = round(sim, 4)
            scored.append((sim, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]
