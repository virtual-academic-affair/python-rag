"""Service for handling class registration requests"""
import json
import logging
from typing import Dict, Any, Optional

import os
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from app.services.orchestration.llm_factory import build_extraction_llm, chain_prompt, env_thinking_level

from app.models.schemas import InternalData
from pydantic import BaseModel, Field
from enum import Enum

class ClassRegistrationAction(str, Enum):
    REGISTER = "REGISTER"
    CANCEL = "CANCEL"
    REQUEST_OPEN = "REQUEST_OPEN"


class ClassRegistrationSubject(BaseModel):
    action: ClassRegistrationAction
    subjectName: str = Field(..., min_length=1)
    className: Optional[str] = None
    subjectCode: Optional[str] = None


class ClassRegistrationRecord(BaseModel):
    email_id: str = Field(..., min_length=1)
    student_code: str = Field(..., min_length=1)
    academic_year: int = Field(..., ge=0)
    student_name: Optional[str] = None
    subjects: list[ClassRegistrationSubject] = Field(default_factory=list)
logger = logging.getLogger(__name__)


def _numbered_lines(text: str) -> str:
    lines = (text or "").splitlines()
    out = []
    for i, line in enumerate(lines, start=1):
        out.append(f"{i:03d}: {line}")
    return "\n".join(out)


class ClassRegistrationService:
    """Service for processing class registration requests"""

    def __init__(self, llm):
        self.llm = llm

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key and hasattr(llm, "google_api_key"):
            api_key = llm.google_api_key

        from config.settings import settings

        self.extraction_llm = build_extraction_llm(
            api_key=api_key or "",
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            thinking_level=env_thinking_level(),
        )

        self.extraction_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content="""You are a Data Parser engine responsible for converting Vietnamese student emails into Database Records.

### TARGET DATABASE SCHEMA
You must extract data to fit exactly into these fields:

**1. Student Info (Parent Entity):**
- `student_code` (String, Required): Extract MSSV/Mã SV. **If not found, return null.**
- `student_name` (String, Optional): Extract full name. **If not found, return null.**
- `academic_year` (Int, Required): Extract the cohort number from "Khóa". **If not found, return 0.**

**2. Registration Details (Child Entity - List):**
- `action` (Enum, Required): "REGISTER", "CANCEL", "REQUEST_OPEN".
- `subjectName` (String, Required): The name of the subject.
- `subjectCode` (String, Optional): The course code. **If not found, return null.**
- `className` (String, Optional): The specific class code. **If not found, return null.**

### STRICT VALIDATION RULES (DO NOT IGNORE)
1. **NO HALLUCINATION:** Do NOT invent, guess, or infer data that is not explicitly written in the text.
   - Bad: Email says "Đăng ký C++" -> Output className: "20CTT1" (Invented).
   - Good: Email says "Đăng ký C++" -> Output className: null.

2. **MISSING MANDATORY FIELDS:**
   - If a required field (like `student_code` or `className` for REGISTER) is missing in the text, you MUST set it to `null`.
   - Do NOT try to fill it to satisfy the database schema. The application code will handle the validation error.

3. **VERBATIM:** Extract names and codes exactly as they appear in the email.

4. **IMPLICIT INFO:** Only `academic_year` can be inferred from context (e.g., "K67" -> 67). All other fields must be explicit.

### FEW-SHOT EXAMPLES

**Input 1 (Full Info):**
"Em là Nguyễn Văn A, MSSV: 2112345, Khóa 67. Em xin đăng ký môn Lập trình C lớp 21CLC."

**Output 1:**
{
  "student_info": {
    "student_code": "2112345",
    "student_name": "Nguyễn Văn A",
    "academic_year": 67
  },
  "details": [
    {
      "action": "REGISTER",
      "subjectName": "Lập trình C",
      "subjectCode": null,
      "className": "21CLC"
    }
  ]
}

**Input 2 (Missing Info - Anti-Hallucination Test):**
"Em muốn hủy môn Mạng máy tính. (Email không có tên, không có mã SV)"

**Output 2:**
{
  "student_info": {
    "student_code": null,
    "student_name": null,
    "academic_year": 0
  },
  "details": [
    {
      "action": "CANCEL",
      "subjectName": "Mạng máy tính",
      "subjectCode": null,
      "className": null
    }
  ]
}

### FINAL OUTPUT FORMAT
Return ONLY valid JSON matching the structure above.
"""
                ),
                HumanMessage(content="Title: {title}\n\nCONTENT (numbered lines):\n{content_lines}"),
            ]
        )

    async def process(self, internal_data: InternalData, title: str, content: str) -> ClassRegistrationRecord:
        logger.info("Extracting class registration data...")
        extracted_data = await self._extract_data(title, content)

        if not extracted_data:
            raise ValueError("Failed to extract class registration data")

        email_id = ""
        if isinstance(internal_data, dict):
            email_id = str(internal_data.get("mail_id") or internal_data.get("email_id") or "")
        else:
            email_id = str(getattr(internal_data, "mail_id", "") or getattr(internal_data, "email_id", ""))

        student_info = extracted_data.get("student_info") or {}
        details = extracted_data.get("details") or []

        record = ClassRegistrationRecord(
            email_id=email_id,
            student_code=str(student_info.get("student_code") or ""),
            academic_year=int(student_info.get("academic_year") or 0),
            student_name=student_info.get("student_name"),
            subjects=[ClassRegistrationSubject(**d) for d in details if isinstance(d, dict)],
        )

        logger.info("Final class_registration record: %s", record.model_dump_json())
        return record

    async def _extract_data(self, title: str, content: str) -> Optional[Dict[str, Any]]:
        try:
            chain = chain_prompt(self.extraction_prompt, self.extraction_llm)
            content_lines = _numbered_lines(content)
            result = await chain.ainvoke(
                {"title": title, "content_lines": content_lines, "content": content}
            )

            response_text = (result.content or "").strip()
            logger.info("Raw LLM response: %s", response_text)

            if "```json" in response_text:
                response_text = (
                    response_text.split("```json")[1].split("```")[0].strip()
                )
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            if not response_text.startswith("{"):
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}")
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    response_text = response_text[start_idx : end_idx + 1]

            parsed = json.loads(response_text)
            logger.info("Parsed JSON: %s", json.dumps(parsed, ensure_ascii=False))
            return parsed

        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON from LLM response: %s", e)
            return None
        except Exception as e:
            logger.error("Error in data extraction: %s", e, exc_info=True)
            return None

