"""Service for handling class registration requests"""
import json
import logging
from typing import Dict, Any, Optional, List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import (
    InternalData,
    StudentData,
    ClassData,
    CourseData,
    CourseClassPair,
    ClassRegistrationResponse
)

logger = logging.getLogger(__name__)


class ClassRegistrationService:
    """Service for processing class registration requests"""
    
    def __init__(self, llm: ChatGoogleGenerativeAI):
        """
        Initialize ClassRegistrationService.
        
        Args:
            llm: LangChain LLM instance
        """
        self.llm = llm
        # Create a separate LLM instance with higher temperature for extraction
        # This helps with parsing complex structured content
        from langchain_google_genai import ChatGoogleGenerativeAI
        import os
        
        # Get API key from environment or from the existing LLM instance
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key and hasattr(llm, 'google_api_key'):
            api_key = llm.google_api_key
        
        self.extraction_llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash-lite",
            google_api_key=api_key,
            temperature=0.3,  # Higher temperature for better extraction
            convert_system_message_to_human=True
        )
        
        self.extraction_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="""You are an expert at extracting structured information from student emails about class registration.
            
            CRITICAL RULES:
            1. ONLY extract information that is EXPLICITLY mentioned in the email. DO NOT invent, guess, or create any data.
            2. If information is not found in the email, use empty string "" for text fields and 0 for numbers.
            3. Be extremely precise with codes, names, and numbers - extract them exactly as written.
            
            Analyze the email title and content to extract the following information:
            
            For student information, extract EXACTLY as written in the email:
            - code: student ID/code (mã sinh viên) - extract the exact code mentioned
            - name: full student name (tên sinh viên) - extract the exact name
            - class: student's class/program (lớp) - extract the exact class code
            - year: enrollment year as integer (khóa học) - extract the exact year mentioned
            
            For class and course information:
            - IMPORTANT: Each class belongs to ONE course. Class and course information go together.
            - When extracting, ensure the course code and class code match what is mentioned together in the email.
            - If email mentions "Mã lớp: CNPM01" and "Môn học: Nhập môn lập trình (CSC101)", extract exactly:
              * class code: "CNPM01" (exactly as written)
              * course code: "CSC101" (exactly as written, not "CS101" or any variation)
              * course name: "Nhập môn lập trình" (exactly as written)
            
            For class information:
            - code: the specific class code (mã lớp) - extract EXACTLY as written (e.g., "CNPM01" not "CNPM_01" or "CNPM1")
            - day: day of the week (first 3 letters in uppercase, e.g., MON, TUE, WED) (thứ) - convert from Vietnamese if needed
              * "Thứ 2" or "Monday" -> "MON"
              * "Thứ 3" or "Tuesday" -> "TUE"
              * etc.
            - time: class start time in HH:MM:SS format (thời gian) - extract exactly as written
              * "07:30:00" not "7:30" or "07:30"
            - action: Determine based on email content:
              * "join" - if email says "đăng ký", "đăng ký lớp", "thêm lớp", "enroll", "register" (registering for a NEW class)
              * "cancel" - if email says "hủy lớp", "rút lớp", "cancel", "withdraw" (canceling an EXISTING class)
              * "change" - ONLY if email explicitly mentions "đổi lớp" or "change from class X to class Y" (changing from one class to another)
            
            For course information:
            - code: the course/subject code (mã môn) - extract EXACTLY as written in parentheses or as mentioned
              * If email says "(CSC101)", extract "CSC101" exactly, not "CS101" or "CSC-101"
            - name: the course/subject name (tên môn) - extract exactly as written
              * If email says "Nhập môn lập trình", extract exactly that, not "Lập trình cơ bản" or variations
            
            ACTION LOGIC (VERY IMPORTANT):
            - Đăng ký mới (new registration): Return 1 class object with action "join"
            - Hủy lớp (cancel class): Return 1 class object with action "cancel"
            - Đổi lớp (change class): Return 2 class objects:
              * First object: old class with action "cancel" (the class being left)
              * Second object: new class with action "join" (the class being joined)
            - DO NOT create 2 objects unless the email explicitly mentions changing from one class to another.
            
            For course information, extract EXACTLY as written:
            - code: the course/subject code (mã môn) - extract exactly (e.g., "CSC101" not "CS101")
            - name: the course/subject name (tên môn) - extract exactly as written
            
            IMPORTANT: The email may contain MULTIPLE courses with MULTIPLE classes. Extract ALL of them.
            
            Return ONLY a valid JSON object with this structure:
            {
                "student": {
                    "code": "...",
                    "name": "...",
                    "class": "...",
                    "year": 2022
                },
                "course_class_pairs": [
                    {
                        "course": {
                            "code": "...",
                            "name": "..."
                        },
                        "classes": [
                            {
                                "code": "...",
                                "day": "...",
                                "time": "HH:MM:SS",
                                "action": "join" or "cancel"
                            }
                        ]
                    }
                ]
            }
            
            STRUCTURE RULES:
            - "course_class_pairs" is an array that can contain MULTIPLE course-class pairs
            - Each course-class pair contains:
              * One "course" object (course code and name)
              * One "classes" array with 1 or more class objects
            - For đổi lớp (change class): the classes array should contain 2 objects (cancel old + join new) for the SAME course
            - For đăng ký mới or hủy lớp: the classes array should contain 1 object
            - If email mentions multiple different courses, create separate course_class_pairs for each course
            
            EXAMPLES:
            
            Example 1 - Multiple registrations:
            Email: "1. Đăng ký lớp học phần mới:\n- Môn học: Cơ sở dữ liệu (CSD201)\n- Mã lớp: CSD01\n- Thứ: Thứ 3\n- Thời gian: 09:00:00\n\n2. Đăng ký thêm lớp học phần:\n- Môn học: Mạng máy tính (MMT301)\n- Mã lớp: MMT02\n- Thứ: Thứ 5\n- Thời gian: 13:30:00"
            Response: {
              "student": {"code": "...", "name": "...", "class": "...", "year": 2022},
              "course_class_pairs": [
                {
                  "course": {"code": "CSD201", "name": "Cơ sở dữ liệu"},
                  "classes": [{"code": "CSD01", "day": "TUE", "time": "09:00:00", "action": "join"}]
                },
                {
                  "course": {"code": "MMT301", "name": "Mạng máy tính"},
                  "classes": [{"code": "MMT02", "day": "THU", "time": "13:30:00", "action": "join"}]
                }
              ]
            }
            
            Example 2 - Cancel class:
            Email: "Hủy lớp học phần:\n- Môn học: Lập trình hướng đối tượng (OOP202)\n- Mã lớp: OOP03\n- Thứ: Thứ 4\n- Thời gian: 07:30:00"
            Response: {
              "student": {"code": "...", "name": "...", "class": "...", "year": 2022},
              "course_class_pairs": [
                {
                  "course": {"code": "OOP202", "name": "Lập trình hướng đối tượng"},
                  "classes": [{"code": "OOP03", "day": "WED", "time": "07:30:00", "action": "cancel"}]
                }
              ]
            }
            
            Example 3 - Change class:
            Email: "Đổi lớp học phần:\n- Môn học: Nhập môn lập trình (CSC101)\n- Từ lớp: CNPM01 (Thứ 2, 07:30:00) sang lớp: CNPM02 (Thứ 2, 14:00:00)"
            Response: {
              "student": {"code": "...", "name": "...", "class": "...", "year": 2022},
              "course_class_pairs": [
                {
                  "course": {"code": "CSC101", "name": "Nhập môn lập trình"},
                  "classes": [
                    {"code": "CNPM01", "day": "MON", "time": "07:30:00", "action": "cancel"},
                    {"code": "CNPM02", "day": "MON", "time": "14:00:00", "action": "join"}
                  ]
                }
              ]
            }
            
            Example 4 - Complex (multiple actions):
            Email with: "Đăng ký CSD01 (CSD201)", "Hủy OOP03 (OOP202)", "Đổi từ CNPM01 sang CNPM02 (CSC101)"
            Response: {
              "student": {"code": "...", "name": "...", "class": "...", "year": 2022},
              "course_class_pairs": [
                {"course": {"code": "CSD201", "name": "Cơ sở dữ liệu"}, "classes": [{"code": "CSD01", "day": "MON", "time": "09:00:00", "action": "join"}]},
                {"course": {"code": "OOP202", "name": "Lập trình hướng đối tượng"}, "classes": [{"code": "OOP03", "day": "WED", "time": "07:30:00", "action": "cancel"}]},
                {"course": {"code": "CSC101", "name": "Nhập môn lập trình"}, "classes": [{"code": "CNPM01", "day": "MON", "time": "07:30:00", "action": "cancel"}, {"code": "CNPM02", "day": "MON", "time": "14:00:00", "action": "join"}]}
              ]
            }
            
            Example 5 - Real complex request with multiple registrations, cancellations, and changes:
            Title: "Yêu cầu đăng ký, hủy và đổi lớp học phần"
            Content: "Tôi là sinh viên Trần Thị B, mã sinh viên: 22127260, lớp: 22CLC02, khóa 2022.\n\n1. Đăng ký lớp học phần mới:\n- Môn học: Cơ sở dữ liệu (CSD201)\n- Mã lớp: CSD01\n- Thứ: Thứ 3 (Tuesday)\n- Thời gian: 09:00:00\n\n2. Đăng ký thêm lớp học phần:\n- Môn học: Mạng máy tính (MMT301)\n- Mã lớp: MMT02\n- Thứ: Thứ 5 (Thursday)\n- Thời gian: 13:30:00\n\n3. Hủy lớp học phần:\n- Môn học: Lập trình hướng đối tượng (OOP202)\n- Mã lớp: OOP03\n- Thứ: Thứ 4 (Wednesday)\n- Thời gian: 07:30:00\n\n4. Hủy lớp học phần:\n- Môn học: Kiến trúc máy tính (KTM201)\n- Mã lớp: KTM01\n- Thứ: Thứ 6 (Friday)\n- Thời gian: 10:00:00\n\n5. Đổi lớp học phần:\n- Môn học: Nhập môn lập trình (CSC101)\n- Từ lớp: CNPM01 (Thứ 2, 07:30:00) sang lớp: CNPM02 (Thứ 2, 14:00:00)"
            Response: {
              "student": {"code": "22127260", "name": "Trần Thị B", "class": "22CLC02", "year": 2022},
              "course_class_pairs": [
                {"course": {"code": "CSD201", "name": "Cơ sở dữ liệu"}, "classes": [{"code": "CSD01", "day": "TUE", "time": "09:00:00", "action": "join"}]},
                {"course": {"code": "MMT301", "name": "Mạng máy tính"}, "classes": [{"code": "MMT02", "day": "THU", "time": "13:30:00", "action": "join"}]},
                {"course": {"code": "OOP202", "name": "Lập trình hướng đối tượng"}, "classes": [{"code": "OOP03", "day": "WED", "time": "07:30:00", "action": "cancel"}]},
                {"course": {"code": "KTM201", "name": "Kiến trúc máy tính"}, "classes": [{"code": "KTM01", "day": "FRI", "time": "10:00:00", "action": "cancel"}]},
                {"course": {"code": "CSC101", "name": "Nhập môn lập trình"}, "classes": [{"code": "CNPM01", "day": "MON", "time": "07:30:00", "action": "cancel"}, {"code": "CNPM02", "day": "MON", "time": "14:00:00", "action": "join"}]}
              ]
            }
            
            PARSING TIPS:
            - Look for numbered lists (1., 2., 3., etc.) - each number is usually a separate course/class request
            - Look for "Môn học:" or "Môn:" followed by course name and code in parentheses like "(CSD201)"
            - Look for "Mã lớp:" followed by the class code
            - Look for "Thứ:" followed by day of week (Thứ 2 = MON, Thứ 3 = TUE, Thứ 4 = WED, Thứ 5 = THU, Thứ 6 = FRI)
            - Look for "Thời gian:" followed by time in HH:MM:SS format
            - Look for "Từ lớp: ... sang lớp: ..." pattern for class changes
            - Student info is usually at the beginning: "mã sinh viên:", "lớp:", "khóa"
            
            CRITICAL REMINDERS:
            - You MUST extract ALL courses and classes mentioned in the email - do not skip any
            - Group classes by their course (each course has its own course_class_pair in the array)
            - Extract all codes, names, and numbers EXACTLY as written - do NOT abbreviate, modify, or create variations
            - For student information: extract mã sinh viên, tên sinh viên, lớp, khóa from the email
            - The "course_class_pairs" array MUST contain at least one pair if the email mentions any course/class
            - If the email mentions multiple courses, create multiple course_class_pairs
            - If information is missing, use empty string "" for text or 0 for numbers
            - DO NOT return an empty course_class_pairs array if the email contains course/class information
            - ALWAYS return valid JSON - no extra text before or after the JSON object"""),
            HumanMessage(content="Title: {title}\n\nContent: {content}")
        ])

    async def process(
        self,
        internal_data: InternalData,
        title: str,
        content: str
    ) -> ClassRegistrationResponse:
        """Process class registration request and return structured response."""
        try:
            logger.info("Extracting class registration data...")
            extracted_data = await self._extract_data(title, content)
            
            if not extracted_data:
                raise ValueError("Failed to extract class registration data")
            
            logger.info(f"Successfully extracted data: {extracted_data}")
            
            # Create student data
            student_data = StudentData(
                code=extracted_data["student"]["code"],
                name=extracted_data["student"]["name"],
                class_name=extracted_data["student"]["class"],
                year=extracted_data["student"]["year"]
            )
            
            # Process course_class_pairs
            course_class_pairs = []
            
            # Check if we have the new format (course_class_pairs) or old format (course + classes)
            if "course_class_pairs" in extracted_data and isinstance(extracted_data["course_class_pairs"], list) and len(extracted_data["course_class_pairs"]) > 0:
                # New format: multiple course-class pairs
                logger.info(f"Processing {len(extracted_data['course_class_pairs'])} course_class_pairs")
                for pair in extracted_data["course_class_pairs"]:
                    course_info = pair.get("course", {})
                    classes_info = pair.get("classes", [])
                    
                    # Create course data
                    course_data = CourseData(
                        code=course_info.get("code", ""),
                        name=course_info.get("name", "")
                    )
                    
                    # Process classes for this course
                    class_data_list = []
                    for class_info in classes_info:
                        action = class_info.get("action", "join").lower()
                        
                        # Handle "change" action
                        if action == "change":
                            # This shouldn't happen in new format, but handle it
                            logger.warning("Change action found in course_class_pairs, this should be handled as cancel+join")
                            action = "join"
                        
                        if action not in ["join", "cancel"]:
                            action = "join"
                        
                        class_data = ClassData(
                            code=class_info.get("code", ""),
                            day=class_info.get("day", "MON"),
                            time=class_info.get("time", "00:00:00"),
                            action=action
                        )
                        class_data_list.append(class_data)
                    
                    # If no classes, create a default one
                    if not class_data_list:
                        logger.warning(f"No classes found for course {course_data.code}, creating default class data")
                        class_data_list.append(ClassData(
                            code="",
                            day="MON",
                            time="00:00:00",
                            action="join"
                        ))
                    
                    # Create course-class pair
                    course_class_pair = CourseClassPair(
                        course=course_data,
                        classes=class_data_list
                    )
                    course_class_pairs.append(course_class_pair)
            
            elif ("course" in extracted_data and extracted_data["course"]) or ("classes" in extracted_data and extracted_data["classes"]):
                # Old format: single course with classes (backward compatibility)
                logger.info("Using old format (single course), converting to course_class_pairs")
                course_info = extracted_data["course"]
                classes_info = extracted_data["classes"]
                
                # Create course data
                course_data = CourseData(
                    code=course_info.get("code", ""),
                    name=course_info.get("name", "")
                )
                
                # Process classes
                class_data_list = []
                for class_info in classes_info:
                    action = class_info.get("action", "join").lower()
                    
                    # Handle "change" action - split into cancel and join
                    if action == "change":
                        # Create old class (cancel) if old_code is provided
                        if class_info.get("old_code"):
                            old_class_data = ClassData(
                                code=class_info.get("old_code", ""),
                                day=class_info.get("old_day", "MON"),
                                time=class_info.get("old_time", "00:00:00"),
                                action="cancel"
                            )
                            class_data_list.append(old_class_data)
                        
                        # Add new class with join action
                        new_class_data = ClassData(
                            code=class_info.get("code", ""),
                            day=class_info.get("day", "MON"),
                            time=class_info.get("time", "00:00:00"),
                            action="join"
                        )
                        class_data_list.append(new_class_data)
                    else:
                        if action not in ["join", "cancel"]:
                            action = "join"
                        
                        class_data = ClassData(
                            code=class_info.get("code", ""),
                            day=class_info.get("day", "MON"),
                            time=class_info.get("time", "00:00:00"),
                            action=action
                        )
                        class_data_list.append(class_data)
                
                # If no classes, create a default one
                if not class_data_list:
                    logger.warning("No classes found, creating default class data")
                    class_data_list.append(ClassData(
                        code="",
                        day="MON",
                        time="00:00:00",
                        action="join"
                    ))
                
                # Create course-class pair
                course_class_pair = CourseClassPair(
                    course=course_data,
                    classes=class_data_list
                )
                course_class_pairs.append(course_class_pair)
            else:
                # No course information found
                logger.error("No course information found in extracted data!")
                logger.error(f"Extracted data keys: {list(extracted_data.keys())}")
                logger.error(f"Extracted data: {extracted_data}")
                # Don't create default, let it fail or return empty
                # This will help identify the issue
            
            # Validate that we have at least one course-class pair
            if not course_class_pairs:
                logger.error("No course-class pairs created! This should not happen.")
                raise ValueError("Failed to extract any course-class pairs from the email. Please check the email content and LLM response.")
            
            # Create response
            response = ClassRegistrationResponse(
                internal=internal_data,
                types=["class_registration"],
                student=student_data,
                courses=course_class_pairs
            )
            
            logger.info(f"Successfully created ClassRegistrationResponse with {len(course_class_pairs)} course-class pairs")
            return response
            
        except Exception as e:
            logger.error(f"Error processing class registration: {str(e)}", exc_info=True)
            raise

    async def _extract_data(
        self,
        title: str,
        content: str
    ) -> Optional[Dict[str, Any]]:
        """Extract structured data from email."""
        try:
            chain = self.extraction_prompt | self.extraction_llm
            result = await chain.ainvoke({
                "title": title,
                "content": content
            })
            
            # Parse the JSON response
            response_text = result.content.strip()
            logger.info(f"Raw LLM response: {response_text}")  # Changed to INFO to see in logs
            
            # Try to extract JSON from markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            # Try to find JSON object in the response if it's not clean
            if not response_text.startswith("{"):
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}")
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    response_text = response_text[start_idx:end_idx+1]
            
            logger.info(f"Parsed JSON text: {response_text}")
            extracted_data = json.loads(response_text)
            logger.info(f"Extracted data keys: {list(extracted_data.keys())}")
            logger.info(f"Extracted data full: {json.dumps(extracted_data, ensure_ascii=False, indent=2)}")
            
            # Validate and ensure the structure is complete
            # Support both new format (course_class_pairs) and old format (course + classes) for backward compatibility
            
            # Extract student information
            if "student" not in extracted_data:
                logger.warning("No student information found in extracted data")
                extracted_data["student"] = {"code": "", "name": "", "class": "", "year": 2022}
            else:
                student = extracted_data["student"]
                student.setdefault("code", "")
                student.setdefault("name", "")
                student.setdefault("class", "")
                student.setdefault("year", 2022)
                logger.info(f"Student extracted: {student}")
            
            # Validate course_class_pairs (new format)
            if "course_class_pairs" in extracted_data:
                logger.info(f"Found course_class_pairs in extracted data")
                if not isinstance(extracted_data["course_class_pairs"], list):
                    logger.warning("course_class_pairs is not a list, converting to empty list")
                    extracted_data["course_class_pairs"] = []
                else:
                    logger.info(f"Found {len(extracted_data['course_class_pairs'])} course_class_pairs")
                    for idx, pair in enumerate(extracted_data["course_class_pairs"]):
                        # Ensure course exists
                        if "course" not in pair:
                            logger.warning(f"Pair {idx} missing course, adding default")
                            pair["course"] = {"code": "", "name": ""}
                        else:
                            pair["course"].setdefault("code", "")
                            pair["course"].setdefault("name", "")
                            logger.debug(f"Pair {idx} course: {pair['course']}")
                        
                        # Ensure classes exists and is a list
                        if "classes" not in pair:
                            logger.warning(f"Pair {idx} missing classes, adding empty list")
                            pair["classes"] = []
                        elif not isinstance(pair["classes"], list):
                            logger.warning(f"Pair {idx} classes is not a list, converting to empty list")
                            pair["classes"] = []
                        else:
                            logger.debug(f"Pair {idx} has {len(pair['classes'])} classes")
                            # Ensure all classes have required fields
                            for class_info in pair["classes"]:
                                class_info.setdefault("code", "")
                                class_info.setdefault("day", "MON")
                                class_info.setdefault("time", "00:00:00")
                                if "action" not in class_info:
                                    class_info["action"] = "join"
                                elif class_info["action"] not in ["join", "cancel"]:
                                    class_info["action"] = "join"
            else:
                logger.warning("No course_class_pairs found in extracted data, checking for old format")
            
            # Backward compatibility: validate old format (course + classes)
            if "course" in extracted_data or "classes" in extracted_data:
                logger.info("Found old format (course/classes), will convert to course_class_pairs")
                if "classes" not in extracted_data or not isinstance(extracted_data["classes"], list):
                    # Try to use "class" (singular) if "classes" doesn't exist
                    if "class" in extracted_data:
                        class_info = extracted_data["class"]
                        action = class_info.get("action", "join")
                        extracted_data["classes"] = [{
                            "code": class_info.get("code", ""),
                            "day": class_info.get("day", "MON"),
                            "time": class_info.get("time", "00:00:00"),
                            "action": action
                        }]
                    else:
                        extracted_data["classes"] = [{
                            "code": "",
                            "day": "MON",
                            "time": "00:00:00",
                            "action": "join"
                        }]
                else:
                    # Ensure all classes have action
                    for class_info in extracted_data["classes"]:
                        class_info.setdefault("code", "")
                        class_info.setdefault("day", "MON")
                        class_info.setdefault("time", "00:00:00")
                        if "action" not in class_info:
                            class_info["action"] = "join"
                        elif class_info["action"] not in ["join", "cancel"]:
                            class_info["action"] = "join"
                
                if "course" not in extracted_data:
                    extracted_data["course"] = {"code": "", "name": ""}
                else:
                    course = extracted_data["course"]
                    course.setdefault("code", "")
                    course.setdefault("name", "")
            
            return extracted_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {str(e)}")
            logger.error(f"Raw response: {result.content if 'result' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"Error in data extraction: {str(e)}", exc_info=True)
            return None

