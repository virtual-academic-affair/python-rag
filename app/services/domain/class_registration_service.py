"""Service for handling class registration requests"""
import json
import logging
from typing import Dict, Any, Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import (
    InternalData,
    StudentData,
    ClassData,
    CourseData,
    CourseClassPair,
    ClassRegistrationResponse,
)

def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _is_verbatim_substring(quote: Any, source_text: str) -> bool:
    if quote is None:
        return True
    if not isinstance(quote, str):
        return True
    q = quote.strip()
    if q == "":
        return True
    return _normalize_text(q) in _normalize_text(source_text)


logger = logging.getLogger(__name__)


def _numbered_lines(text: str) -> str:
    lines = (text or "").splitlines()
    out = []
    for i, line in enumerate(lines, start=1):
        out.append(f"{i:03d}: {line}")
    return "\n".join(out)


def _extract_student_name_from_content(content: str) -> str:
    # Deterministic extraction to avoid LLM placeholders like "Nguyễn Văn A"
    # Supports simple Vietnamese patterns: "Em tên là ..." / "Tôi tên là ..."
    text = content or ""
    for anchor in ["Em tên là", "Tôi tên là"]:
        idx = text.lower().find(anchor.lower())
        if idx == -1:
            continue
        after = text[idx + len(anchor) :]
        after = after.strip(" \t\u00a0")
        for sep in ["\n", ",", ".", ";"]:
            cut = after.find(sep)
            if cut != -1:
                after = after[:cut]
                break
        return after.strip(" \t\u00a0")
    return ""


class ClassRegistrationService:
    """Service for processing class registration requests"""

    def __init__(self, llm: ChatGoogleGenerativeAI):
        self.llm = llm
        from langchain_google_genai import ChatGoogleGenerativeAI
        import os

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key and hasattr(llm, "google_api_key"):
            api_key = llm.google_api_key

        from config.settings import settings

        self.extraction_llm = ChatGoogleGenerativeAI(
            model=settings.LLM_MODEL,
            google_api_key=api_key,
            temperature=settings.LLM_TEMPERATURE,
            convert_system_message_to_human=True,
        )

        self.extraction_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content="""You are an information extraction engine for Vietnamese student registration emails.

You MUST use ANCHOR-BASED extraction with multiple Vietnamese variants.

STEP 1: QUOTES (VERBATIM)
Extract quotes ONLY by copying exact substrings from the email using ONE of the allowed anchors for each field.
- Anchors are case-insensitive.
- Allowed separators after anchors: ':', '-', '–', '—'.
- The quote is the text immediately after the anchor+separator, trimmed.
- Stop the quote at the first occurrence of one of: newline, ',', '.', ';'.

STUDENT FIELDS
- student.code anchors: "Mã sinh viên", "MSSV", "MSV", "Mã SV".
- student.name anchors: "Em tên là", "Tôi tên là", "Họ và tên", "Họ tên", "Tên".
- student.class anchors: "Lớp/Khoa", "Lớp", "Khoa", "Ngành".
- student.year anchors (optional): "Khóa", "Năm học". If not found, keep quote null.

COURSE FIELDS
- course_code anchors: "mã học phần", "mã môn", "mã HP", "mã MH".
  The quote for course_code is the first alphanumeric code token after the anchor (e.g., CSC23231).
- course_name extraction (only if clearly present near the code):
  * Pattern 1: "học phần <NAME> – mã học phần <CODE>" => quote <NAME> exactly.
  * Pattern 2: "<NAME> ( <CODE> )" => quote <NAME> exactly.

ACTION
- action quote:
  * If the email contains "đăng ký" or "xin đăng ký" => quote "đăng ký".
  * If it contains "hủy" or "rút" => quote "hủy".

If you cannot find an anchor for a field, set its quote to null. DO NOT guess.
If you find at least one course_code, you MUST produce quotes.courses with at least that course. Do NOT invent additional courses.

IMPORTANT ABOUT COURSES:
- If you find at least one course_code quote, you MUST output exactly one course quote object for that course.
- Do NOT invent additional courses.

STEP 2: STRUCTURED
Build the final structured JSON strictly from the quotes.
- Every non-empty/non-null field in data MUST be identical to its corresponding quote.
- If class_code/day/time are not present, set them to null (do NOT guess).
- action in data MUST be "join" or "cancel". If quote.action is "đăng ký" then use "join".

EXAMPLES (copy-substring behavior):
- Email line: "Mã số sinh viên: 2212321," => student.code quote MUST be "2212321".
- Email line: "Em tên là ABC," => student.name quote MUST be "ABC".
- Email line: "Lớp/Khoa: 123/CNTT." => student.class quote MUST be "123/CNTT".
- Email fragment: "đăng ký học phần Nhập môn học máy – mã học phần CSC23231" =>
  * course_code quote MUST be "CSC23231"
  * course_name quote MUST be "Nhập môn học máy"

BANNED PLACEHOLDERS:
- Do NOT output placeholder Vietnamese names like "Nguyễn Văn A".
- Do NOT output random student codes like "20210601".
- Do NOT output unrelated course names like "Cấu trúc dữ liệu và giải thuật".
OUTPUT FORMAT
Return ONLY JSON with this exact structure (no markdown):
{
  "quotes": {
    "student": {"code": null, "name": null, "class": null, "year": null},
    "courses": [
      {"course_code": null, "course_name": null, "class_code": null, "day": null, "time": null, "action": null}
    ]
  },
  "data": {
    "student": {"code": "", "name": "", "class": "", "year": 0},
    "course_class_pairs": [
      {
        "course": {"code": "", "name": ""},
        "classes": [
          {"code": "", "day": null, "time": null, "action": "join"}
        ]
      }
    ]
  }
}

If no course_code is found in the email, set quotes.courses to [] and data.course_class_pairs to [].
"""
                ),
                HumanMessage(content="Title: {title}\n\nCONTENT (numbered lines):\n{content_lines}"),
            ]
        )

    async def process(
        self, internal_data: InternalData, title: str, content: str
    ) -> ClassRegistrationResponse:
        logger.info("Extracting class registration data...")
        extracted_data = await self._extract_data(title, content)

        if not extracted_data:
            raise ValueError("Failed to extract class registration data")

        student_data = StudentData(
            code=extracted_data["student"].get("code", ""),
            name=extracted_data["student"].get("name", ""),
            class_name=extracted_data["student"].get("class", ""),
            year=extracted_data["student"].get("year", 0),
        )

        course_class_pairs = []
        if (
            "course_class_pairs" in extracted_data
            and isinstance(extracted_data["course_class_pairs"], list)
            and len(extracted_data["course_class_pairs"]) > 0
        ):
            for pair in extracted_data["course_class_pairs"]:
                course_info = pair.get("course", {})
                classes_info = pair.get("classes", [])

                course_data = CourseData(
                    code=course_info.get("code", ""),
                    name=course_info.get("name", ""),
                )

                class_data_list = []
                for class_info in classes_info:
                    raw_action = class_info.get("action", "join")
                    action = (raw_action or "join").strip().lower()

                    # Accept Vietnamese action words, normalize to schema values
                    if action in ["đăng ký", "dang ky", "xin đăng ký", "xin dang ky"]:
                        action = "join"
                    elif action in ["hủy", "huy", "rút", "rut"]:
                        action = "cancel"

                    if action not in ["join", "cancel"]:
                        action = "join"

                    code = class_info.get("code")
                    if code is None:
                        code = ""

                    class_data_list.append(
                        ClassData(
                            code=code,
                            day=class_info.get("day") or None,
                            time=class_info.get("time") or None,
                            action=action,
                        )
                    )

                if not class_data_list:
                    class_data_list.append(
                        ClassData(code="", day=None, time=None, action="join")
                    )

                course_class_pairs.append(
                    CourseClassPair(course=course_data, classes=class_data_list)
                )

        if not course_class_pairs:
            raise ValueError("Failed to extract any course-class pairs from the email")

        return ClassRegistrationResponse(
            internal=internal_data,
            types=["class_registration"],
            student=student_data,
            courses=course_class_pairs,
        )

    async def _extract_data(self, title: str, content: str) -> Optional[Dict[str, Any]]:
        try:
            chain = self.extraction_prompt | self.extraction_llm
            content_lines = _numbered_lines(content)
            result = await chain.ainvoke(
                {"title": title, "content_lines": content_lines, "content": content}
            )

            response_text = (result.content or "").strip()
            logger.info(f"Raw LLM response: {response_text}")

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

            # New quote-then-structure format returns {"quotes": ..., "data": {...}}
            quotes = parsed.get("quotes") if isinstance(parsed, dict) else None
            extracted_data = parsed.get("data") if isinstance(parsed, dict) else None
            if not isinstance(extracted_data, dict):
                extracted_data = parsed if isinstance(parsed, dict) else {}

            if "student" not in extracted_data:
                extracted_data["student"] = {"code": "", "name": "", "class": "", "year": 0}
            else:
                extracted_data["student"].setdefault("code", "")
                extracted_data["student"].setdefault("name", "")
                extracted_data["student"].setdefault("class", "")
                extracted_data["student"].setdefault("year", 0)

            if "course_class_pairs" not in extracted_data or not isinstance(
                extracted_data["course_class_pairs"], list
            ):
                extracted_data["course_class_pairs"] = []

            # Validate that data fields are copied from quotes (no hallucinated values)
            if isinstance(quotes, dict):
                q_student = quotes.get("student") or {}
                q_courses = quotes.get("courses") or []

                # Quotes must be verbatim substrings of the original email text.
                source_text = f"{title}\n{content}"
                if not _is_verbatim_substring(q_student.get("code"), source_text):
                    logger.warning(
                        "Rejecting non-verbatim quote student.code=%r", q_student.get("code")
                    )
                    q_student["code"] = None
                if not _is_verbatim_substring(q_student.get("name"), source_text):
                    logger.warning(
                        "Rejecting non-verbatim quote student.name=%r", q_student.get("name")
                    )
                    q_student["name"] = None
                if not _is_verbatim_substring(q_student.get("class"), source_text):
                    logger.warning(
                        "Rejecting non-verbatim quote student.class=%r", q_student.get("class")
                    )
                    q_student["class"] = None

                if isinstance(q_courses, list):
                    for q in q_courses:
                        if not isinstance(q, dict):
                            continue
                        for k in [
                            "course_code",
                            "course_name",
                            "class_code",
                            "day",
                            "time",
                            "action",
                        ]:
                            if not _is_verbatim_substring(q.get(k), source_text):
                                logger.warning(
                                    "Rejecting non-verbatim quote %s=%r", k, q.get(k)
                                )
                                q[k] = None

                # Deterministic override for student.name if present in email
                deterministic_name = _extract_student_name_from_content(content)
                if deterministic_name:
                    extracted_data["student"]["name"] = deterministic_name

                # Deterministic override for action based on original email text
                combined_text = f"{title}\n{content}".lower()
                if "đăng ký" in combined_text or "xin đăng ký" in combined_text:
                    for pair in extracted_data.get("course_class_pairs") or []:
                        classes = pair.get("classes") or []
                        for c in classes:
                            c["action"] = "join"
                elif "hủy" in combined_text or "rút" in combined_text:
                    for pair in extracted_data.get("course_class_pairs") or []:
                        classes = pair.get("classes") or []
                        for c in classes:
                            c["action"] = "cancel"

                def _must_come_from_quote(value: Any, quote: Any) -> bool:
                    if value is None:
                        return True
                    if isinstance(value, str):
                        if value == "":
                            return True
                        return isinstance(quote, str) and value == quote
                    if isinstance(value, int):
                        if value == 0:
                            return True
                        return (isinstance(quote, int) and value == quote) or (
                            isinstance(quote, str) and str(value) == quote
                        )
                    return True

                # Student
                if not _must_come_from_quote(extracted_data["student"].get("code"), q_student.get("code")):
                    logger.warning("Rejecting hallucinated student.code=%r (quote=%r)", extracted_data["student"].get("code"), q_student.get("code"))
                    extracted_data["student"]["code"] = ""
                if not _must_come_from_quote(extracted_data["student"].get("name"), q_student.get("name")):
                    logger.warning("Rejecting hallucinated student.name=%r (quote=%r)", extracted_data["student"].get("name"), q_student.get("name"))
                    extracted_data["student"]["name"] = ""
                if not _must_come_from_quote(extracted_data["student"].get("class"), q_student.get("class")):
                    logger.warning("Rejecting hallucinated student.class=%r (quote=%r)", extracted_data["student"].get("class"), q_student.get("class"))
                    extracted_data["student"]["class"] = ""

                # Courses/classes
                for idx, pair in enumerate(extracted_data.get("course_class_pairs") or []):
                    q = q_courses[idx] if idx < len(q_courses) and isinstance(q_courses, list) else {}
                    q_course_code = (q or {}).get("course_code")
                    q_course_name = (q or {}).get("course_name")

                    course = pair.get("course") or {}
                    if not _must_come_from_quote(course.get("code"), q_course_code):
                        logger.warning("Rejecting hallucinated course.code=%r (quote=%r)", course.get("code"), q_course_code)
                        course["code"] = ""
                    if not _must_come_from_quote(course.get("name"), q_course_name):
                        logger.warning("Rejecting hallucinated course.name=%r (quote=%r)", course.get("name"), q_course_name)
                        course["name"] = ""
                    pair["course"] = course

                    classes = pair.get("classes") or []
                    if classes:
                        q_class_code = (q or {}).get("class_code")
                        q_day = (q or {}).get("day")
                        q_time = (q or {}).get("time")
                        q_action = (q or {}).get("action")

                        c0 = classes[0]
                        if not _must_come_from_quote(c0.get("code"), q_class_code):
                            logger.warning("Rejecting hallucinated class.code=%r (quote=%r)", c0.get("code"), q_class_code)
                            c0["code"] = ""
                        if not _must_come_from_quote(c0.get("day"), q_day):
                            logger.warning("Rejecting hallucinated class.day=%r (quote=%r)", c0.get("day"), q_day)
                            c0["day"] = None
                        if not _must_come_from_quote(c0.get("time"), q_time):
                            logger.warning("Rejecting hallucinated class.time=%r (quote=%r)", c0.get("time"), q_time)
                            c0["time"] = None
                        if not _must_come_from_quote(c0.get("action"), q_action):
                            logger.warning("Rejecting hallucinated class.action=%r (quote=%r)", c0.get("action"), q_action)
                            c0["action"] = "join"
                        classes[0] = c0
                        pair["classes"] = classes

            logger.info("Final extracted class_registration data: %s", json.dumps(extracted_data, ensure_ascii=False))
            return extracted_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error in data extraction: {str(e)}", exc_info=True)
            return None

