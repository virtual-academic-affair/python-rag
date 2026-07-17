"""
Seed script to import FAQs from a JSON file into the system.
Usage: python scripts/seed_faqs.py --file scripts/sample_faqs.json
"""
import asyncio
import json
import argparse
import sys
import os

from beanie import init_beanie

# Add the project root to the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.database import Database
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.services.faq_service import get_faq_service
from app.modules.metadata.services.metadata_service import get_metadata_service

async def main(file_path: str = None):
    if not file_path:
        parser = argparse.ArgumentParser(description="Seed FAQs into the system.")
        parser.add_argument("--file", required=True, help="Path to JSON file containing FAQs")
        args = parser.parse_args()
        file_path = args.file
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading file: {e}")
        return
        
    if not isinstance(data, (dict, list)):
        print("Invalid format: Expected a JSON object with 'faqs' or a JSON array of FAQ objects.")
        return

    if isinstance(data, dict) and data.get("candidates"):
        print("Invalid format: FAQ candidates are no longer supported. Remove the non-empty 'candidates' field.")
        return

    faqs_data = data.get("faqs", []) if isinstance(data, dict) else data
        
    # Connect to DB
    await Database.connect()
    
    await init_beanie(
        database=Database.get_db(),
        document_models=[FaqDocument]
    )
    
    faq_svc = await get_faq_service()
    validator = get_metadata_service()
    success_count = 0
    error_count = 0
        
    print(f"Starting import of {len(faqs_data)} FAQs...")
    for i, item in enumerate(faqs_data):
        try:
            question = item.get("question")
            answer_rich_text = item.get("answer_rich_text")
            
            if not question or not answer_rich_text:
                print(f"Skipping item {i}: missing question or answer_rich_text")
                error_count += 1
                continue
                
            raw_meta = item.get("metadata_filter") or {}
            
            is_valid, errors, meta_model = validator.validate_and_parse_faq_metadata(raw_meta)
            if not is_valid:
                print(f"Skipping item {i}: Invalid metadata: {', '.join(errors)} (Raw: {raw_meta})")
                error_count += 1
                continue
            
            metadata_filter = meta_model.model_dump()
            
            existing = await faq_svc.check_duplicate_question(question)
            if existing:
                print(f"[{i+1}/{len(faqs_data)}] Skipped (already exists): {question[:50]}...")
                continue

            await faq_svc.create_faq(
                question=question,
                answer_rich_text=answer_rich_text,
                metadata_filter=metadata_filter,
                source="seed",
                lecturer_only=bool(item.get("lecturer_only", False)),
            )
            success_count += 1
            print(f"[{i+1}/{len(faqs_data)}] Created: {question[:50]}...")
            
        except Exception as e:
            print(f"Error creating FAQ {i}: {e}")
            error_count += 1
            
    await Database.disconnect()
    
    print(f"\nImport complete! Success FAQs: {success_count}, Errors: {error_count}")

if __name__ == "__main__":
    asyncio.run(main())
