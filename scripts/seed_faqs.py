"""
Seed script to import FAQs from a JSON file into the system.
Usage: python scripts/seed_faqs.py --file scripts/sample_faqs.json
"""
import asyncio
import json
import argparse
import sys
import os

# Add the project root to the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.config import settings
from app.core.database import Database
from app.modules.faq.service import get_faq_service
from app.modules.metadata.service import get_metadata_service
from app.core.text_utils import remove_accents
from app.core.format_utils import rich_text_to_markdown
from datetime import datetime, timezone
from bson import ObjectId

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
        
    if not isinstance(data, dict) and not isinstance(data, list):
        print("Invalid format: Expected a JSON object with 'faqs' and 'candidates' or a JSON array of FAQ objects.")
        return
        
    faqs_data = data.get("faqs", []) if isinstance(data, dict) else data
    candidates_data = data.get("candidates", []) if isinstance(data, dict) else []
        
    # Connect to DB
    await Database.connect()
    
    faq_svc = await get_faq_service()
    validator = get_metadata_service()
    db = Database.get_db()
    
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
            
            question_unaccented = remove_accents(question)
            existing = await faq_svc._faq_repo.find_one({"question_unaccented": question_unaccented})
            if existing:
                print(f"[{i+1}/{len(faqs_data)}] Skipped (already exists): {question[:50]}...")
                continue

            await faq_svc.create_faq(
                question=question,
                answer_rich_text=answer_rich_text,
                metadata_filter=metadata_filter,
                source="seed"
            )
            success_count += 1
            print(f"[{i+1}/{len(faqs_data)}] Created: {question[:50]}...")
            
        except Exception as e:
            print(f"Error creating FAQ {i}: {e}")
            error_count += 1
            
    print(f"\nSeeding dummy FAQ Candidates ({len(candidates_data)} items)...")
    
    dummy_candidates = []
    for item in candidates_data:
        question = item.get("question", "Unknown question")
        answer_rt = item.get("answer_draft_rich_text", "")
        answer_md = rich_text_to_markdown(answer_rt)
        
        raw_meta = item.get("metadata_filter_suggestion") or {}
        _, _, meta_model = validator.validate_and_parse_faq_metadata(raw_meta)
        meta_filter = meta_model.model_dump() if meta_model else {}
        
        dummy_candidates.append({
            "_id": ObjectId(),
            "question": question,
            "question_unaccented": remove_accents(question),
            "answer_draft_rich_text": answer_rt,
            "answer_draft_markdown": answer_md,
            "answer_draft_unaccented": remove_accents(answer_md),
            "metadata_filter_suggestion": meta_filter,
            "source_type": item.get("source_type", "chat"),
            "source_log_ids": [str(ObjectId()) for _ in range(item.get("similar_count", 2))],
            "similar_count": item.get("similar_count", 2),
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": None,
            "synthesis_batch_id": "seed_batch_001",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
    
    if dummy_candidates:
        try:
            await db.get_collection(Database.FAQ_CANDIDATES).insert_many(dummy_candidates)
            print(f"Created {len(dummy_candidates)} dummy FAQ Candidates.")
        except Exception as e:
            print(f"Error creating dummy FAQ Candidates: {e}")
    else:
        print("No dummy FAQ Candidates found to seed.")
        
    await Database.disconnect()
    
    print(f"\nImport complete! Success FAQs: {success_count}, Errors: {error_count}")

if __name__ == "__main__":
    asyncio.run(main())
