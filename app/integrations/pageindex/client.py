import logging
import os
import time
import uuid
import asyncio
import concurrent.futures
from pathlib import Path
from typing import Optional, List, Dict, Any

import PyPDF2

from .page_index import page_index
from .page_index_md import md_to_tree
from .retrieve import get_document, get_document_structure, get_page_content
from .utils import ConfigLoader, remove_fields
from app.integrations.storage.client import r2_storage
from app.modules.files.toc_tree.repository import FileTocTreeRepository
from app.integrations.redis.client import get_redis_client
from app.core.config import settings

logger = logging.getLogger(__name__)
MD_CACHE_TTL_SECONDS = 3600  # 1 hour


def _normalize_retrieve_model(model: str) -> str:
    """Preserve supported Agents SDK prefixes and route other provider paths via LiteLLM."""
    passthrough_prefixes = ("litellm/", "openai/")
    if not model or "/" not in model:
        return model
    if model.startswith(passthrough_prefixes):
        return model
    return f"litellm/{model}"



class PageIndexClient:
    """
    A client for indexing and retrieving document content.
    Flow: index() -> get_document() / get_document_structure() / get_page_content()
    """
    def __init__(self, api_key: str = None, model: str = None, retrieve_model: str = None, workspace: str = None):
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["GOOGLE_API_KEY"] = api_key
        elif not os.getenv("OPENAI_API_KEY") and os.getenv("CHATGPT_API_KEY"):
            os.environ["OPENAI_API_KEY"] = os.getenv("CHATGPT_API_KEY")
        self.workspace = Path(workspace).expanduser() if workspace else None
        overrides = {}
        if model:
            overrides["model"] = model
        if retrieve_model:
            overrides["retrieve_model"] = retrieve_model
        opt = ConfigLoader().load(overrides or None)
        self.model = opt.model
        self.retrieve_model = _normalize_retrieve_model(opt.retrieve_model or self.model)
        if self.workspace:
            self.workspace.mkdir(parents=True, exist_ok=True)
        self._redis = get_redis_client()
        self._toc_repo = None
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, doc_id: str) -> asyncio.Lock:
        if doc_id not in self._locks:
            self._locks[doc_id] = asyncio.Lock()
        return self._locks[doc_id]

    @property
    def redis(self):
        return self._redis

    @property
    def toc_repo(self):
        if self._toc_repo is None:
            self._toc_repo = FileTocTreeRepository()
        return self._toc_repo

    async def _save_doc_to_cache(self, doc_id: str, data: dict):
        """Save document metadata to Redis cache with TTL."""
        await self.redis.connect()
        # Ensure we don't store double nesting or sensitive internal paths if possible, 
        # but for now we follow the existing structure.
        await self.redis.set_json(f"pageindex:doc:{doc_id}", data, ex=MD_CACHE_TTL_SECONDS)

    async def _get_doc_from_cache(self, doc_id: str) -> Optional[dict]:
        """Retrieve document metadata from Redis cache."""
        await self.redis.connect()
        return await self.redis.get_json(f"pageindex:doc:{doc_id}")

    async def index(self, file_path: str, mode: str = "auto", doc_id: str = None) -> str:
        """Index a document. Returns a document_id."""
        file_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        doc_id = doc_id or str(uuid.uuid4())
        ext = os.path.splitext(file_path)[1].lower()

        is_pdf = ext == '.pdf'
        is_md = ext in ['.md', '.markdown']

        doc_data = {}

        if mode == "pdf" or (mode == "auto" and is_pdf):
            logger.info(f"Indexing PDF: {file_path}")
            result = await asyncio.to_thread(
                page_index,
                doc=file_path,
                model=self.model,
                toc_check_page_num=settings.PAGEINDEX_TOC_CHECK_PAGE_NUM,
                max_page_num_each_node=settings.PAGEINDEX_MAX_PAGE_NUM_EACH_NODE,
                max_token_num_each_node=settings.PAGEINDEX_MAX_TOKEN_NUM_EACH_NODE,
                if_add_node_summary=settings.PAGEINDEX_IF_ADD_NODE_SUMMARY,
                if_add_node_text=settings.PAGEINDEX_IF_ADD_NODE_TEXT,
                if_add_node_id=settings.PAGEINDEX_IF_ADD_NODE_ID,
                if_add_doc_description=settings.PAGEINDEX_IF_ADD_DOC_DESCRIPTION
            )
            
            # Extract per-page text
            def _extract_pages():
                pages = []
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    for i, page in enumerate(pdf_reader.pages, 1):
                        pages.append({'page': i, 'content': page.extract_text() or ''})
                return pages

            pages = await asyncio.to_thread(_extract_pages)

            doc_data = {
                'id': doc_id,
                'type': 'pdf',
                'path': file_path,
                'doc_name': result.get('doc_name', ''),
                'doc_description': result.get('doc_description', ''),
                'page_count': len(pages),
                'structure': result['structure'],
                'pages': pages,
            }

        elif mode == "md" or (mode == "auto" and is_md):
            logger.info(f"Indexing Markdown: {file_path}")
            # md_to_tree is async
            result = await md_to_tree(
                md_path=file_path,
                if_thinning=False,
                min_token_threshold=settings.PAGEINDEX_MAX_TOKEN_NUM_EACH_NODE,
                if_add_node_summary=settings.PAGEINDEX_IF_ADD_NODE_SUMMARY,
                summary_token_threshold=settings.PAGEINDEX_SUMMARY_TOKEN_THRESHOLD,
                model=self.model,
                if_add_doc_description=settings.PAGEINDEX_IF_ADD_DOC_DESCRIPTION,
                if_add_node_text=settings.PAGEINDEX_IF_ADD_NODE_TEXT,
                if_add_node_id=settings.PAGEINDEX_IF_ADD_NODE_ID
            )

            doc_data = {
                'id': doc_id,
                'type': 'md',
                'path': file_path,
                'doc_name': result.get('doc_name', ''),
                'doc_description': result.get('doc_description', ''),
                'line_count': result.get('line_count', 0),
                'structure': result['structure'],
            }
        else:
            raise ValueError(f"Unsupported file format for: {file_path}")

        logger.info(f"Indexing complete. Document ID: {doc_id}")
        await self._save_doc_to_cache(doc_id, doc_data)
        return doc_id

    async def index_md_content(self, md_path: str, doc_id: str, doc_name: str) -> dict:
        """Helper for async ingestion flow."""
        # PageIndex internal md_to_tree is async
        result = await md_to_tree(
            md_path=md_path,
            if_thinning=False,
            min_token_threshold=settings.PAGEINDEX_MAX_TOKEN_NUM_EACH_NODE,
            if_add_node_summary=settings.PAGEINDEX_IF_ADD_NODE_SUMMARY,
            summary_token_threshold=settings.PAGEINDEX_SUMMARY_TOKEN_THRESHOLD,
            model=self.model,
            if_add_doc_description=settings.PAGEINDEX_IF_ADD_DOC_DESCRIPTION,
            if_add_node_text=settings.PAGEINDEX_IF_ADD_NODE_TEXT,
            if_add_node_id=settings.PAGEINDEX_IF_ADD_NODE_ID
        )
        
        doc_data = {
            'id': doc_id,
            'type': 'md',
            'path': md_path,
            'doc_name': doc_name or result.get('doc_name', ''),
            'doc_description': result.get('doc_description', ''),
            'line_count': result.get('line_count', 0),
            'structure': result['structure'],
        }
        await self._save_doc_to_cache(doc_id, doc_data)
        
        return {
            "doc_name": doc_data["doc_name"],
            "doc_description": doc_data["doc_description"],
            "line_count": doc_data["line_count"],
            "structure": doc_data["structure"],
        }

    async def evict_doc(self, doc_id: str) -> None:
        """Remove a document from shared Redis cache and delete local markdown cache file."""
        # Remove from Redis
        await self.redis.connect()
        await self.redis.delete(f"pageindex:doc:{doc_id}")
        
        # Remove local cached .md file
        if self.workspace:
            local_path = self.workspace / f"{doc_id}.md"
            if local_path.exists():
                try:
                    await asyncio.to_thread(local_path.unlink)
                    logger.info(f"Evicted markdown cache for doc {doc_id}")
                except Exception as e:
                    logger.warning(f"Failed to evict markdown cache for {doc_id}: {e}")

    async def cleanup_expired_artifacts(self, max_age_seconds: int = MD_CACHE_TTL_SECONDS) -> int:
        """Scan workspace/artifacts and delete files older than max_age_seconds."""
        if not self.workspace or not self.workspace.exists():
            return 0
            
        def _cleanup():
            count = 0
            now = time.time()
            for item in self.workspace.glob("*.md"):
                if item.is_file():
                    mtime = item.stat().st_mtime
                    if (now - mtime) > max_age_seconds:
                        try:
                            item.unlink()
                            count += 1
                            logger.info(f"Cleaned up expired artifact: {item.name}")
                        except Exception as e:
                            logger.warning(f"Failed to delete expired artifact {item}: {e}")
            return count

        return await asyncio.to_thread(_cleanup)

    async def _check_and_refresh_cache(self, doc_id: str, md_storage_path: str):
        """Check if local markdown exists and is fresh. If not, download from R2."""
        if not self.workspace or not md_storage_path:
            return

        lock = self._get_lock(doc_id)
        async with lock:
            local_path = self.workspace / f"{doc_id}.md"
            now = time.time()
            
            needs_download = False
            if not local_path.exists():
                needs_download = True
            else:
                # Check TTL using modification time
                mtime = local_path.stat().st_mtime
                if (now - mtime) > MD_CACHE_TTL_SECONDS:
                    needs_download = True

            if needs_download:
                try:
                    logger.info(f"Refreshing markdown cache for {doc_id} from R2 path: {md_storage_path}")
                    file_obj = await r2_storage.download_file(md_storage_path)
                    if file_obj:
                        def _write():
                            # Download to temporary file then atomically replace to avoid corrupt reads
                            tmp_path = local_path.with_suffix('.md.tmp')
                            with open(tmp_path, "wb") as f:
                                f.write(file_obj.read())
                            tmp_path.replace(local_path)
                        await asyncio.to_thread(_write)
                        logger.info(f"Successfully cached {doc_id}.md to {local_path}")
                    else:
                        logger.error(f"R2 download returned empty object for {doc_id} at {md_storage_path}")
                except Exception as e:
                    logger.error(f"Failed to refresh markdown cache for {doc_id}: {e}")

    async def _ensure_doc_loaded(self, doc_id: str, background_download: bool = False):
        """Load full document from Redis or MongoDB on demand."""
        doc = await self._get_doc_from_cache(doc_id)
        local_md_path_obj = self.workspace / f"{doc_id}.md" if self.workspace else None
        
        needs_db_reload = False
        if not doc or doc.get('structure') is None:
            needs_db_reload = True
        elif local_md_path_obj and not local_md_path_obj.exists():
            # If doc is in Redis but file is missing locally, we still need to refresh file
            pass 

        if needs_db_reload:
            full = await self.toc_repo.find_by_file_id(doc_id)
            if not full:
                logger.warning(f"Metadata for document {doc_id} not found in MongoDB.")
                return

            md_storage_path = full.get('markdown_storage_path')
            if md_storage_path:
                if background_download:
                    asyncio.create_task(self._check_and_refresh_cache(doc_id, md_storage_path))
                else:
                    await self._check_and_refresh_cache(doc_id, md_storage_path)
            
            doc = {
                'id': doc_id,
                'type': 'md',
                'path': str(local_md_path_obj) if local_md_path_obj else "",
                'doc_name': full.get('doc_name', ''),
                'doc_description': full.get('doc_description', ''),
                'line_count': full.get('line_count', 0),
                'structure': full.get('structure', []),
            }
            await self._save_doc_to_cache(doc_id, doc)
        else:
            # Document exists in Redis, ensure local file is also present if it was previously cached
            # (In a true stateless environment, we'd always check/refresh cache)
            # For brevity, let's assume if it's in Redis, we might still need the file for content retrieval.
            if doc.get('type') == 'md':
                md_storage_path = doc.get('markdown_storage_path')
                if not md_storage_path:
                    # Try to get from DB if not in cache
                    full = await self.toc_repo.find_by_file_id(doc_id)
                    md_storage_path = full.get('markdown_storage_path') if full else None
                
                if md_storage_path:
                    if background_download:
                        asyncio.create_task(self._check_and_refresh_cache(doc_id, md_storage_path))
                    else:
                        await self._check_and_refresh_cache(doc_id, md_storage_path)

        # Update local timestamp for file cleanup logic
        if local_md_path_obj and local_md_path_obj.exists():
            await asyncio.to_thread(local_md_path_obj.touch)

        return doc

    async def get_document(self, doc_id: str) -> str:
        """Return document metadata JSON."""
        doc = await self._ensure_doc_loaded(doc_id)
        if not doc: return "{}"
        # get_document expects dict of documents
        return get_document({doc_id: doc}, doc_id)

    async def get_document_structure(self, doc_id: str) -> str:
        """Return document tree structure JSON."""
        doc = await self._ensure_doc_loaded(doc_id, background_download=True)
        if not doc: return "{}"
        return get_document_structure({doc_id: doc}, doc_id)

    async def get_page_content(self, doc_id: str, pages: str) -> str:
        """Return page content for the given pages string."""
        doc = await self._ensure_doc_loaded(doc_id)
        if not doc: return ""
        return get_page_content({doc_id: doc}, doc_id, pages)

_page_index_client_instance = None

def get_page_index_client():
    global _page_index_client_instance
    if _page_index_client_instance is None:
        m = settings.GEMINI_MODEL
        if "/" not in m:
            m = f"gemini/{m}"
        
        _page_index_client_instance = PageIndexClient(
            api_key=settings.GOOGLE_API_KEY,
            model=m,
            workspace=settings.PAGEINDEX_WORKSPACE
        )
    return _page_index_client_instance