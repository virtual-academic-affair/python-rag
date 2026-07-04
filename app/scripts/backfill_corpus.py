"""
Backfill script: index all existing READY files and active FAQs into the corpus graph.

Usage:
    python -m app.scripts.backfill_corpus
    # or
    python app/scripts/backfill_corpus.py
"""
from __future__ import annotations
import asyncio
import logging
import sys
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    from beanie import init_beanie
    from app.core.database import Database
    from app.modules.files.models.file import FileDocument, FileStatus
    from app.modules.faq.models.faq import FaqDocument
    from app.modules.faq.models.faq_candidate import FaqCandidateDocument
    from app.modules.faq.models.interaction_log import InteractionLogDocument
    from app.modules.files.toc_tree.models.toc_tree import FileTocTree
    from app.modules.chat.models.chat_session import ChatSessionDocument
    from app.modules.chat.models.chat_message import ChatMessageDocument
    from app.modules.forms.models.form import FormDocument
    from app.modules.corpus.models.corpus_node import CorpusNodeDocument
    from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
    from app.modules.corpus.data.seed import seed_corpus
    from app.modules.corpus.services.corpus_index_service import get_corpus_index_service

    await Database.connect()
    db = Database.get_db()

    await init_beanie(
        database=db,
        document_models=[
            FileDocument,
            FileTocTree,
            FaqDocument,
            FaqCandidateDocument,
            InteractionLogDocument,
            ChatSessionDocument,
            ChatMessageDocument,
            FormDocument,
            CorpusNodeDocument,
        ],
    )

    # 1. Seed root + axes
    repo = CorpusNodeRepository()
    seeded = await seed_corpus(repo)
    logger.info(f"[Backfill] seed_corpus: {seeded} nodes created")

    index_svc = get_corpus_index_service()
    files_ok = files_err = faqs_ok = faqs_err = 0

    # 2. Backfill READY files
    BATCH = 100
    skip = 0
    while True:
        batch = await FileDocument.find(
            FileDocument.status == FileStatus.READY
        ).skip(skip).limit(BATCH).to_list()
        if not batch:
            break
        for file_doc in batch:
            fid = str(file_doc.id)
            try:
                meta_dict = file_doc.custom_metadata.model_dump(mode="json") if file_doc.custom_metadata else {}
                await index_svc.index_file(
                    fid,
                    meta_dict,
                    display_name=file_doc.display_name or "",
                    toc_headings=file_doc.table_of_contents or [],
                )
                files_ok += 1
            except Exception as e:
                logger.error(f"[Backfill] index_file failed for {fid}: {e}")
                files_err += 1
        logger.info(f"[Backfill] files processed so far: {files_ok + files_err}")
        skip += BATCH
        if len(batch) < BATCH:
            break

    # 3. Backfill active FAQs
    skip = 0
    while True:
        batch = await FaqDocument.find(
            FaqDocument.is_active == True
        ).skip(skip).limit(BATCH).to_list()
        if not batch:
            break
        for faq in batch:
            fid = str(faq.id)
            try:
                meta_dict = faq.metadata_filter.model_dump(mode="json") if faq.metadata_filter else {}
                await index_svc.index_faq(
                    fid,
                    meta_dict,
                    question=faq.question or "",
                    answer_markdown=faq.answer_markdown or "",
                )
                faqs_ok += 1
            except Exception as e:
                logger.error(f"[Backfill] index_faq failed for {fid}: {e}")
                faqs_err += 1
        logger.info(f"[Backfill] FAQs processed so far: {faqs_ok + faqs_err}")
        skip += BATCH
        if len(batch) < BATCH:
            break

    logger.info(
        f"[Backfill] Done. Files: {files_ok} ok / {files_err} err. "
        f"FAQs: {faqs_ok} ok / {faqs_err} err."
    )
    await Database.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
