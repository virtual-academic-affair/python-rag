from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundException
from app.modules.files.models.file import FileStatus
from app.modules.files.toc_tree.services.toc_tree_service import TocTreeService


def _service(file_doc):
    service = TocTreeService.__new__(TocTreeService)
    service._file_repo = MagicMock()
    service._file_repo.find_by_id = AsyncMock(return_value=file_doc)
    service._repo = MagicMock()
    service._repo.find_by_file_id = AsyncMock(return_value=SimpleNamespace(file_id="file1"))
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["student", "lecture"])
async def test_toc_tree_hides_non_ready_file_from_non_admin(role):
    service = _service(
        SimpleNamespace(id="file1", status=FileStatus.PROCESSING, lecturer_only=False)
    )

    with pytest.raises(NotFoundException):
        await service.get_toc_tree("file1", role)

    service._repo.find_by_file_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_toc_tree_allows_admin_to_read_non_ready_file():
    service = _service(
        SimpleNamespace(id="file1", status=FileStatus.PROCESSING, lecturer_only=False)
    )

    result = await service.get_toc_tree("file1", "admin")

    assert result.file_id == "file1"


@pytest.mark.asyncio
async def test_toc_tree_hides_lecturer_only_file_from_student():
    service = _service(
        SimpleNamespace(id="file1", status=FileStatus.READY, lecturer_only=True)
    )

    with pytest.raises(NotFoundException):
        await service.get_toc_tree("file1", "student")
