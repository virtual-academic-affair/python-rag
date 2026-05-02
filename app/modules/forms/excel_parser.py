import io
from typing import List, Dict, Any, Optional
import openpyxl
from openpyxl.cell.rich_text import CellRichText
from app.modules.forms.schemas import FormImportRow
from app.integrations.excel import get_column_index, cell_to_rich_text, get_cell_value

def parse_excel_to_form_rows(
    file_bytes: bytes,
    document_type_col: str,
    content_link_col: str,
    notes_col: Optional[str] = None,
    start_row: int = 2,
    preview_limit: Optional[int] = None
) -> Dict[str, Any]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=False, rich_text=True)
    ws = wb.active

    dt_idx = get_column_index(ws, document_type_col)
    cl_idx = get_column_index(ws, content_link_col)
    nt_idx = get_column_index(ws, notes_col) if notes_col else None

    if not dt_idx or not cl_idx:
        return {"rows": [], "total_previewed": 0, "error": "Could not find required columns"}

    rows = []
    for r_idx, row in enumerate(ws.iter_rows(min_row=start_row), start=start_row):
        if all(cell.value is None for cell in row):
            continue
        
        
        dt_raw = get_cell_value(row[dt_idx - 1])
        dt_val = str(dt_raw).strip() if dt_raw is not None else None
        
        # Link extraction with formatting and hyperlinks support
        cl_val = cell_to_rich_text(row[cl_idx - 1])

        # Assuming notes require rich text formatted processing
        nt_val = cell_to_rich_text(row[nt_idx - 1]) if nt_idx else None

        # Ignore empty required fields rows without error
        if not dt_val or not cl_val:
            continue

        item = FormImportRow(
            document_type=dt_val,
            content_link=cl_val,
            notes=nt_val,
            is_valid=True
        )
        rows.append(item)
        if preview_limit and len(rows) >= preview_limit:
            break

    return {"rows": rows, "total_previewed": len(rows)}
