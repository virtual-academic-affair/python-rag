"""LangChain service for classification and data extraction"""
import os
import json
import logging
from typing import Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage
from app.models.schemas import (
    InternalData, 
    StudentData, 
    ClassData, 
    CourseData,
    ClassRegistrationResponse, 
    OtherResponse
)

logger = logging.getLogger(__name__)


class LangChainClassifier:
    """LangChain classifier for student email classification and data extraction"""
    
    def __init__(self, api_key: str):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-pro",
            google_api_key=api_key,
            temperature=0.1
        )
        
        self.classification_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert at classifying student emails and requests. 
            Analyze the provided email title and content and classify it into one of these categories:
            - class_registration: For requests related to registering for classes, enrolling in courses
            - administrative_requests: For general administrative matters, document requests, etc.
            - graduation: For graduation-related requests, thesis, final projects
            - academic_affairs: For academic issues, grades, transcripts, academic policies
            - other: For anything that doesn't fit the above categories
            
            Respond with ONLY the category name, nothing else."""),
            ("human", "Title: {title}\n\nContent: {content}")
        ])
        
        self.extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert at extracting structured information from student emails.
            Analyze the email title and content to extract the following information and return it as a JSON object:
            
            For student information, extract:
            - code: student ID/code (mã sinh viên)
            - name: full student name (tên sinh viên)
            - class: student's class/program (lớp)
            - year: enrollment year as integer (khóa học)
            
            For class information, extract:
            - code: the specific class code (mã lớp)
            - day: day of the week (first 3 letters in uppercase, e.g., MON, TUE, WED) (thứ)
            - time: class start time in HH:MM:SS format (thời gian)
            
            For course information, extract:
            - code: the course/subject code (mã môn)
            - name: the course/subject name (tên môn)
            
            If any information is not found in the email, use reasonable defaults or leave empty strings.
            Return ONLY a valid JSON object with this structure:
            {
                "student": {
                    "code": "...",
                    "name": "...",
                    "class": "...",
                    "year": 2022
                },
                "class": {
                    "code": "...",
                    "day": "...",
                    "time": "HH:MM:SS"
                },
                "course": {
                    "code": "...",
                    "name": "..."
                }
            }"""),
            ("human", "Title: {title}\n\nContent: {content}")
        ])

    async def classify_request(self, title: str, content: str) -> str:
        """Classify the request into one of the predefined categories."""
        try:
            chain = self.classification_prompt | self.llm
            result = await chain.ainvoke({
                "title": title,
                "content": content
            })
            
            classification = result.content.strip().lower()
            
            # Validate classification
            valid_classifications = [
                "class_registration", "administrative_requests", 
                "graduation", "academic_affairs", "other"
            ]
            
            if classification not in valid_classifications:
                logger.warning(f"Invalid classification: {classification}, defaulting to 'other'")
                return "other"
                
            return classification
            
        except Exception as e:
            logger.error(f"Error in classification: {str(e)}")
            return "other"

    async def extract_class_registration_data(
        self, 
        title: str, 
        content: str
    ) -> Optional[Dict[str, Any]]:
        """Extract structured data for class registration requests."""
        try:
            chain = self.extraction_prompt | self.llm
            result = await chain.ainvoke({
                "title": title,
                "content": content
            })
            
            # Parse the JSON response - try to extract JSON from markdown code blocks if present
            response_text = result.content.strip()
            
            # Try to extract JSON from markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            extracted_data = json.loads(response_text)
            
            # Validate the structure
            required_fields = ["student", "class", "course"]
            for field in required_fields:
                if field not in extracted_data:
                    raise ValueError(f"Missing required field: {field} in extracted data")
                
            return extracted_data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {str(e)}")
            logger.error(f"Raw response: {result.content if 'result' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"Error in data extraction: {str(e)}")
            return None

    async def process_request(
        self, 
        internal_data: InternalData, 
        title: str, 
        content: str
    ):
        """Process the complete request and return appropriate response."""
        try:
            # First, classify the request
            classification = await self.classify_request(title, content)
            
            if classification == "class_registration":
                # Extract detailed information
                extracted_data = await self.extract_class_registration_data(
                    title, 
                    content
                )
                
                if extracted_data:
                    # Create structured response
                    student_data = StudentData(
                        code=extracted_data["student"]["code"],
                        name=extracted_data["student"]["name"],
                        class_name=extracted_data["student"]["class"],
                        year=extracted_data["student"]["year"]
                    )
                    
                    class_data = ClassData(
                        code=extracted_data["class"]["code"],
                        day=extracted_data["class"]["day"],
                        time=extracted_data["class"]["time"]
                    )
                    
                    course_data = CourseData(
                        code=extracted_data["course"]["code"],
                        name=extracted_data["course"]["name"]
                    )
                    
                    return ClassRegistrationResponse(
                        internal=internal_data,
                        types=["class_registration"],
                        student=student_data,
                        class_data=class_data,
                        course=course_data
                    )
                else:
                    # Fallback to other if extraction fails
                    return OtherResponse(
                        internal=internal_data,
                        types=["other"]
                    )
            else:
                # Return simple classification response
                return OtherResponse(
                    internal=internal_data,
                    types=[classification]
                )
                
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}")
            return OtherResponse(
                internal=internal_data,
                types=["other"]
            )

