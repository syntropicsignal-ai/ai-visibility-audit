"""Postgres + pgvector CorpusStore: lazy HF->PG ingest, substring-gated cosine search."""

from __future__ import annotations

import asyncio
import logging
import zlib

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import WildchatCorpus
from app.services.corpus import HF_DATASET_BY_LANG, CorpusHit

logger = logging.getLogger(__name__)

_INGEST_BATCH = 5_000
_HF_PARQUET_FILE = "data/train.parquet"
_PARQUET_COLUMNS = ("text", "source", "intent", "length_mode", "domain", "embedding")

_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_wildchat_corpus_embedding_hnsw "
    "ON wildchat_corpus USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS ix_wildchat_corpus_text_trgm "
    "ON wildchat_corpus USING gin (text gin_trgm_ops)",
)


def _advisory_key(language_code: str) -> int:
    return zlib.crc32(f"wildchat_corpus:{language_code}".encode())


def _read_hf_parquet(dataset_name: str, language_code: str) -> list[dict]:
    from huggingface_hub import hf_hub_download
    from pyarrow import parquet as pq

    path = hf_hub_download(repo_id=dataset_name, filename=_HF_PARQUET_FILE, repo_type="dataset")
    table = pq.read_table(path, columns=list(_PARQUET_COLUMNS))
    cols = {c: table.column(c).to_pylist() for c in _PARQUET_COLUMNS}
    return [
        {
            "lang": language_code,
            "text": cols["text"][i],
            "source": cols["source"][i],
            "intent": cols["intent"][i],
            "length_mode": cols["length_mode"][i],
            "domain": cols["domain"][i],
            "embedding": cols["embedding"][i],
        }
        for i in range(table.num_rows)
    ]


class PgCorpusStore:
    """Holds a session factory so the one-time ingest runs in its own transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def ensure_loaded(self, language_code: str) -> int:
        key = language_code.lower()
        dataset_name = HF_DATASET_BY_LANG.get(key)
        if not dataset_name:
            return 0

        async with self._session_factory() as session:
            # serialize ingest across workers — peers block here, then skip on count>0
            await session.execute(select(func.pg_advisory_xact_lock(_advisory_key(key))))
            count = await self._count(session, key)
            if count:
                return count

            logger.info("Ingesting WildChat dataset %s into Postgres (first use)", dataset_name)
            try:
                rows = await asyncio.to_thread(_read_hf_parquet, dataset_name, key)
            except Exception:
                logger.exception("Failed to download/parse WildChat dataset %s", dataset_name)
                return 0

            for start in range(0, len(rows), _INGEST_BATCH):
                session.add_all(
                    WildchatCorpus(**row) for row in rows[start : start + _INGEST_BATCH]
                )
                await session.flush()
            await self._build_indexes(session)
            await session.commit()
            logger.info("Ingested %d WildChat rows for %s", len(rows), key)
            return len(rows)

    @staticmethod
    async def _build_indexes(session: AsyncSession) -> None:
        # Built post-ingest (pgvector's load-then-index order); declared here, not in
        # the migration, because the corpus arrives lazily at runtime.
        await session.execute(text("SET LOCAL maintenance_work_mem = '512MB'"))
        for ddl in _INDEX_DDL:
            await session.execute(text(ddl))

    async def search(
        self,
        language_code: str,
        query_vec: list[float],
        token_patterns: list[str],
        top_k: int,
    ) -> list[CorpusHit]:
        key = language_code.lower()
        distance = WildchatCorpus.embedding.cosine_distance(query_vec)
        conditions = [WildchatCorpus.lang == key]
        if token_patterns:
            conditions.append(or_(*(WildchatCorpus.text.ilike(p) for p in token_patterns)))
        stmt = (
            select(
                WildchatCorpus.text,
                WildchatCorpus.intent,
                WildchatCorpus.length_mode,
                distance.label("distance"),
            )
            .where(*conditions)
            .order_by(distance)
            .limit(top_k)
        )
        async with self._session_factory() as session:
            # ef_search must be >= rows wanted; iterative scan keeps recall under the gate (pgvector >=0.8)
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {max(top_k, 100)}"))
            await session.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
            rows = (await session.execute(stmt)).all()
        return [
            CorpusHit(
                text=r.text, intent=r.intent, length_mode=r.length_mode, score=1.0 - r.distance
            )
            for r in rows
        ]

    async def texts(self, language_code: str) -> list[str]:
        stmt = select(WildchatCorpus.text).where(WildchatCorpus.lang == language_code.lower())
        async with self._session_factory() as session:
            return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def _count(session: AsyncSession, language_code: str) -> int:
        stmt = (
            select(func.count())
            .select_from(WildchatCorpus)
            .where(WildchatCorpus.lang == language_code)
        )
        return (await session.execute(stmt)).scalar_one()
