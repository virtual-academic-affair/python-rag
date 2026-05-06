import io
import openpyxl
import logging
from typing import List, Dict, Any, Optional, Union
from openpyxl.cell.rich_text import CellRichText

logger = logging.getLogger(__name__)

def get_column_index(sheet, col_identifier: str, header_row: int = 1) -> Optional[int]:
    """
    Convert a column letter (e.g., 'A') or a header name to a 1-based index.
    Searches in row 1 and also in header_row if provided.
    """
    if not col_identifier:
        return None
        
    col_identifier = str(col_identifier).strip()
    
    # 1. Check if it's a digit (e.g., '1', '2')
    if col_identifier.isdigit():
        return int(col_identifier)
        
    # 2. Check if it's a letter (e.g., 'A', 'AB')
    if col_identifier.isalpha():
        from openpyxl.utils import column_index_from_string
        try:
            return column_index_from_string(col_identifier)
        except ValueError:
            pass
            
    # 3. Try to find the name in the header rows
    rows_to_check = {1}
    if header_row and header_row > 1:
        rows_to_check.add(header_row)
        
    for r_idx in sorted(list(rows_to_check)):
        for row in sheet.iter_rows(min_row=r_idx, max_row=r_idx):
            for idx, cell in enumerate(row, start=1):
                cell_value = cell.value
                if cell_value and str(cell_value).strip().lower() == col_identifier.lower():
                    return idx
            
    return None

def cell_to_rich_text(cell) -> str:
    """
    Convert cell content to HTML rich text if it has formatting (bold, italic, underline).
    Handles CellRichText (mixed formatting), full-cell formatting, and hyperlinks.
    """
    val = cell.value
    if val is None:
        return ""
    
    # Handle numbers to avoid '2020.0'
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    
    final_text = ""
    
    # 1. Handle Rich Text (mixed formatting within one cell)
    if isinstance(val, CellRichText):
        parts = []
        for run in val:
            if isinstance(run, str):
                text = run
            else:
                text = run.text
            
            # Handle numbers in rich text runs
            if isinstance(text, float) and text.is_integer():
                text = str(int(text))
            elif not isinstance(text, str):
                text = str(text)

            if isinstance(run, str):
                parts.append(text)
            else:
                font = run.font
                if not text:
                    continue
                if font:
                    # InlineFont uses 'b', 'i', 'u'
                    if getattr(font, 'b', False): text = f"<strong>{text}</strong>"
                    if getattr(font, 'i', False): text = f"<em>{text}</em>"
                    if getattr(font, 'u', None): text = f"<u>{text}</u>"
                parts.append(text)
        final_text = "".join(parts).strip()
    else:
        # 2. Handle Entire Cell Formatting (Plain string + cell font)
        text = str(val).strip()
        font = cell.font
        if font:
            # Font object uses 'bold', 'italic', 'underline'
            if getattr(font, 'bold', False): text = f"<strong>{text}</strong>"
            if getattr(font, 'italic', False): text = f"<em>{text}</em>"
            if getattr(font, 'underline', None): text = f"<u>{text}</u>"
        final_text = text

    # 3. Handle Hyperlinks (wrap around the formatted text)
    if cell.hyperlink and cell.hyperlink.target:
        final_text = f'<a href="{cell.hyperlink.target}">{final_text}</a>'
    
    return final_text

def get_cell_value(cell, format_numbers: bool = True) -> Any:
    """Simple extraction with number formatting."""
    val = cell.value
    if val is None:
        return None
    if format_numbers and isinstance(val, float) and val.is_integer():
        return int(val)
    if isinstance(val, str):
        return val.strip()
    return val
