import os
import uuid
import json
import asyncio
import concurrent.futures
from pathlib import Path

import PyPDF2

from .page_index import page_index
from .page_index_md import md_to_tree
from .retrieve import get_document, get_document_structure, get_page_content
from .utils import ConfigLoader, remove_fields

META_INDEX = "_meta.json"


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

    For agent-based QA, see examples/agentic_vectorless_rag_demo.py.
    """
    def __init__(self, api_key: str = None, model: str = None, retrieve_model: str = None, workspace: str = None):
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["GEMINI_API_KEY"] = api_key
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
        self.documents = {}
        self._toc_repo = None

    @property
    def toc_repo(self):
        if self._toc_repo is None:
            from app.modules.toc_tree.repository import FileTocTreeRepository
            self._toc_repo = FileTocTreeRepository()
        return self._toc_repo

    def index(self, file_path: str, mode: str = "auto", doc_id: str = None) -> str:
        """Index a document. Returns a document_id."""
        file_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        doc_id = doc_id or str(uuid.uuid4())
        ext = os.path.splitext(file_path)[1].lower()

        is_pdf = ext == '.pdf'
        is_md = ext in ['.md', '.markdown']

        if mode == "pdf" or (mode == "auto" and is_pdf):
            print(f"Indexing PDF: {file_path}")
            result = page_index(
                doc=file_path,
                model=self.model,
                if_add_node_summary='yes',
                if_add_node_text='yes',
                if_add_node_id='yes',
                if_add_doc_description='yes'
            )
            # Extract per-page text so queries don't need the original PDF
            pages = []
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for i, page in enumerate(pdf_reader.pages, 1):
                    pages.append({'page': i, 'content': page.extract_text() or ''})

            self.documents[doc_id] = {
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
            print(f"Indexing Markdown: {file_path}")
            coro = md_to_tree(
                md_path=file_path,
                if_thinning=False,
                if_add_node_summary='yes',
                summary_token_threshold=200,
                model=self.model,
                if_add_doc_description='yes',
                if_add_node_text='yes',
                if_add_node_id='yes'
            )
            try:
                # Handle async in sync context
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(asyncio.run, coro).result()
                else:
                    result = asyncio.run(coro)
            except Exception:
                result = asyncio.run(coro)

            self.documents[doc_id] = {
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

        print(f"Indexing complete. Document ID: {doc_id}")
        if self.workspace:
            self._save_doc(doc_id)
        return doc_id

    async def index_md_content(self, md_path: str, doc_id: str, doc_name: str) -> dict:
        """Helper for async ingestion flow."""
        # PageIndex internal md_to_tree is async, so we can await it directly
        result = await md_to_tree(
            md_path=md_path,
            if_thinning=False,
            if_add_node_summary='yes',
            summary_token_threshold=200,
            model=self.model,
            if_add_doc_description='yes',
            if_add_node_text='yes',
            if_add_node_id='yes'
        )
        # We only keep path in memory for get_page_content
        self.documents[doc_id] = {
            'id': doc_id,
            'type': 'md',
            'path': md_path,
            'doc_name': doc_name or result.get('doc_name', ''),
            'doc_description': result.get('doc_description', ''),
            'line_count': result.get('line_count', 0),
        }
        return {
            "doc_name": doc_name or result.get('doc_name', ''),
            "doc_description": result.get('doc_description', ''),
            "line_count": result.get('line_count', 0),
            "structure": result['structure'],
        }

    async def _ensure_doc_loaded(self, doc_id: str):
        """Load full document from MongoDB on demand (structure, path, etc.)."""
        # If we have path but no structure, fetch from MongoDB
        doc = self.documents.get(doc_id)
        
        # If document not in memory at all, fetch metadata from files repo if possible?
        # Actually, PageIndexClient currently doesn't have access to FileRepository.
        # But we can reconstruct basic info from toc_repo.
        
        if not doc or doc.get('structure') is None:
            full = await self.toc_repo.find_by_file_id(doc_id)
            if not full:
                return

            if not doc:
                # Reconstruct cache entry
                self.documents[doc_id] = {
                    'id': doc_id,
                    'type': 'md', # Defaulting to md as per refactor goal
                    'path': str(Path(self.workspace) / f"{doc_id}.md"),
                    'doc_name': full.get('doc_name', ''),
                    'doc_description': full.get('doc_description', ''),
                    'line_count': full.get('line_count', 0),
                }
                doc = self.documents[doc_id]

            doc['structure'] = full.get('structure', [])

    async def get_document(self, doc_id: str) -> str:
        """Return document metadata JSON."""
        await self._ensure_doc_loaded(doc_id)
        return get_document(self.documents, doc_id)

    async def get_document_structure(self, doc_id: str) -> str:
        """Return document tree structure JSON (without text fields)."""
        await self._ensure_doc_loaded(doc_id)
        return get_document_structure(self.documents, doc_id)

    async def get_page_content(self, doc_id: str, pages: str) -> str:
        """Return page content for the given pages string (e.g. '5-7', '3,8', '12')."""
        await self._ensure_doc_loaded(doc_id)
        return get_page_content(self.documents, doc_id, pages)

_page_index_client_instance = None

def get_page_index_client():
    from app.core.config import settings
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
