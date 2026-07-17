"""
RAG Data Snapshot Utility
====================================
Công cụ sao lưu và khôi phục dữ liệu RAG (Metadata & Vectors).

Tác vụ                | Câu lệnh
----------------------|----------------------------------------------------------------------
Sao lưu dữ liệu      | python scripts/snapshot.py export scripts/uploads_result/rag_backup.json
Khởi tạo & Khôi phục | python scripts/init_db.py --restore scripts/uploads_result/rag_backup.json
"""
import asyncio
import io
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

load_dotenv(project_root / ".env")

from app.integrations.storage.client import r2_storage

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

RETIRED_COLLECTIONS = {"faq_candidates", "interaction_logs"}


def sanitize_snapshot_documents(collection_name: str, documents: list[dict]) -> list[dict]:
    """Remove retired FAQ-synthesis fields from data that remains supported."""
    if collection_name == "faqs":
        for document in documents:
            document.pop("candidate_id", None)
    return documents

class SnapshotManager:
    def __init__(self):
        self.mongodb_url = os.getenv("MONGODB_URL")
        self.db_name = os.getenv("MONGODB_DB_NAME", "ai_service")

        self.mongo_client = AsyncIOMotorClient(self.mongodb_url)
        self.db = self.mongo_client[self.db_name]

    async def export_data(self, output_path: str):
        logger.info(f"🚀 Exporting RAG snapshot to {output_path}...")
        
        def json_serializable(obj):
            if isinstance(obj, list):
                return [json_serializable(item) for item in obj]
            if isinstance(obj, dict):
                return {k: json_serializable(v) for k, v in obj.items()}
            if hasattr(obj, 'isoformat'):
                return obj.isoformat()
            return obj

        # 1. Export MongoDB
        logger.info("  Exporting MongoDB collections...")
        snapshot_mongodb = {}
        
        # Get all collections dynamically
        collections = await self.db.list_collection_names()
        # Filter out system collections just in case
        collections = [
            collection
            for collection in collections
            if not collection.startswith("system.") and collection not in RETIRED_COLLECTIONS
        ]
        
        for coll_name in collections:
            docs = await self.db[coll_name].find({}).to_list(None)
            docs = json_serializable(docs)
            docs = sanitize_snapshot_documents(coll_name, docs)
            for doc in docs:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            snapshot_mongodb[coll_name] = docs
            logger.info(f"    ✓ Exported {len(docs)} documents from {coll_name}")
        
        # 2. Download Markdown files from R2
        logger.info("  Downloading Markdown files from R2...")
        try:
            uploads_md_dir = os.path.join(os.path.dirname(__file__), "uploads_md")
            if os.path.exists(uploads_md_dir):
                shutil.rmtree(uploads_md_dir)
            os.makedirs(uploads_md_dir, exist_ok=True)
            
            md_count = 0
            for doc in snapshot_mongodb.get("files", []):
                md_path = doc.get("markdown_storage_path")
                file_id = str(doc.get("_id"))
                if md_path:
                    try:
                        md_bytes = await r2_storage.download_file(md_path)
                        if md_bytes:
                            with open(os.path.join(uploads_md_dir, f"{file_id}.md"), "wb") as f:
                                f.write(md_bytes.getvalue())
                            md_count += 1
                    except Exception as e:
                        logger.warning(f"    ⚠ Could not download {md_path}: {e}")
            logger.info(f"    ✓ Downloaded {md_count} markdown files to local uploads_md")
        except Exception as e:
            logger.warning(f"    ⚠ Failed to process R2 markdown files: {e}")

        snapshot = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "document_count": len(snapshot_mongodb.get("files", [])),
            },
            "mongodb": snapshot_mongodb,
        }

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Export complete! {snapshot['metadata']['document_count']} files.")

    async def import_data(self, input_path: str):
        if not os.path.exists(input_path):
            logger.error(f"❌ Snapshot file not found: {input_path}")
            return

        logger.info(f"🚀 Importing RAG snapshot from {input_path}...")
        with open(input_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
            
        # 1. Import MongoDB
        logger.info("  Restoring MongoDB collections...")
        for coll_name, docs in snapshot.get("mongodb", {}).items():
            if coll_name in RETIRED_COLLECTIONS:
                logger.info("    - Skipped retired collection %s", coll_name)
                continue
            if docs:
                docs = sanitize_snapshot_documents(coll_name, docs)
                # Convert string IDs back to ObjectId
                for d in docs:
                    if "_id" in d and isinstance(d["_id"], str):
                        try:
                            d["_id"] = ObjectId(d["_id"])
                        except:
                            pass
                
                await self.db[coll_name].insert_many(docs)
                logger.info(f"    ✓ Restored {len(docs)} documents to {coll_name}")

        # 2. Import R2 Markdown and Original files
        uploads_md_dir = os.path.join(os.path.dirname(__file__), "uploads_md")
        uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
        if os.path.exists(uploads_md_dir):
            logger.info("  Restoring Markdown and Original files to R2...")
            try:
                md_count = 0
                original_count = 0
                for md_file in os.listdir(uploads_md_dir):
                    if md_file.endswith(".md"):
                        file_id = md_file[:-3]
                        doc = None
                        for d in snapshot.get("mongodb", {}).get("files", []):
                            if str(d.get("_id")) == file_id:
                                doc = d
                                break
                        
                        if doc:
                            # 3.1 Restore Markdown file
                            if doc.get("markdown_storage_path"):
                                with open(os.path.join(uploads_md_dir, md_file), "rb") as f:
                                    bytes_io = io.BytesIO(f.read())
                                    await r2_storage.upload_file(
                                        file=bytes_io, 
                                        object_name=doc.get("markdown_storage_path"), 
                                        content_type="text/markdown"
                                    )
                                    md_count += 1
                            
                            # 3.2 Restore Original file
                            if doc.get("storage_path") and doc.get("original_filename"):
                                original_file_path = os.path.join(uploads_dir, doc.get("original_filename"))
                                if os.path.exists(original_file_path):
                                    with open(original_file_path, "rb") as f:
                                        original_bytes_io = io.BytesIO(f.read())
                                        await r2_storage.upload_file(
                                            file=original_bytes_io,
                                            object_name=doc.get("storage_path"),
                                            content_type=doc.get("mime_type", "application/octet-stream")
                                        )
                                        original_count += 1
                logger.info(f"    ✓ Restored {md_count} markdown files to R2")
                logger.info(f"    ✓ Restored {original_count} original files to R2")
            except Exception as e:
                logger.warning(f"    ⚠ Failed to restore files to R2: {e}")

            
        logger.info("✅ Import complete!")

async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/snapshot.py [export|import] [path]")
        print("Example: python scripts/snapshot.py export scripts/uploads_result/snapshot.json")
        return

    cmd = sys.argv[1]
    path = sys.argv[2]
    
    manager = SnapshotManager()
    if cmd == "export":
        await manager.export_data(path)
    elif cmd == "import":
        await manager.import_data(path)
    else:
        print(f"Unknown command: {cmd}")

if __name__ == "__main__":
    asyncio.run(main())
