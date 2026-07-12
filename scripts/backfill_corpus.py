"""
Backfill script: index all existing READY files and active FAQs into the corpus tree.

Usage:
    python scripts/backfill_corpus.py
"""
from __future__ import annotations
import asyncio
import logging
import sys
import os
from dotenv import load_dotenv

# Add the project root to the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

from beanie import init_beanie

from app.core.database import Database
from app.modules.chat.models.chat_message import ChatMessageDocument
from app.modules.chat.models.chat_session import ChatSessionDocument
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.models.faq_candidate import FaqCandidateDocument
from app.modules.faq.models.interaction_log import InteractionLogDocument
from app.modules.files.models.file import FileDocument, FileStatus
from app.modules.files.toc_tree.models.toc_tree import FileTocTree
from app.modules.forms.models.form import FormDocument
from app.modules.rag.ingestion.corpus_linker import get_corpus_linker
from scripts.seed_corpus import seed_corpus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
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
    await repo.reset_all_links()
    logger.info("[Backfill] cleared existing direct/subtree corpus links")

    corpus_linker = get_corpus_linker()
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
                toc_tree = await FileTocTree.find_one(FileTocTree.file_id == fid)
                await corpus_linker.index_file(
                    fid,
                    display_name=file_doc.display_name or "",
                    doc_description=(toc_tree.doc_description if toc_tree else "") or "",
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
                await corpus_linker.index_faq(
                    fid,
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
