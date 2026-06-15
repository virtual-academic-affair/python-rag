"""
TocTree submodule public API.
"""
from app.modules.files.toc_tree.routers.toc_tree_router import router
from app.modules.files.toc_tree.models.toc_tree import FileTocTree

__all__ = [
    "router",
    "FileTocTree",
]
