from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie.odm.utils.projection import get_projection

from app.modules.files.models.file import FileListProjection
from app.modules.files.repositories.file_repository import FileRepository


def _query_mock():
    query = MagicMock()
    query.count = AsyncMock(return_value=0)
    query.sort.return_value = query
    query.skip.return_value = query
    query.limit.return_value = query
    query.project.return_value = query
    query.to_list = AsyncMock(return_value=[])
    return query


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["list_files", "list_deleted_files"])
async def test_file_lists_apply_compact_projection(method_name):
    query = _query_mock()
    with patch(
        "app.modules.files.repositories.file_repository.FileDocument.find",
        return_value=query,
    ):
        await getattr(FileRepository(), method_name)({}, skip=0, limit=50)

    query.project.assert_called_once_with(FileListProjection)


def test_file_list_projection_excludes_table_of_contents_and_internal_fields():
    projection = get_projection(FileListProjection)

    assert projection is not None
    assert projection["_id"] == 1
    assert "table_of_contents" not in projection
    assert "deleted_corpus_node_keys" not in projection
    assert "display_name_unaccented" not in projection
    assert "storage_bucket" not in projection
