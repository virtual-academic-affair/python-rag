import asyncio
import json
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

"""
RAG Data Snapshot Utility
====================================
Công cụ sao lưu và khôi phục dữ liệu RAG (Metadata & Vectors).

Tác vụ                | Câu lệnh
----------------------|----------------------------------------------------------------------
Sao lưu dữ liệu      | python scripts/snapshot.py export scripts/uploads_result/rag_backup.json
Khởi tạo & Khôi phục | python scripts/init_db.py --restore scripts/uploads_result/rag_backup.json
"""

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SnapshotManager:
    def __init__(self):
        self.mongodb_url = os.getenv("MONGODB_URL")
        self.db_name = os.getenv("MONGODB_DB_NAME", "ai_service")
        self.qdrant_url = settings.QDRANT_URL
        self.qdrant_api_key = settings.QDRANT_API_KEY
        self.collection_name = settings.QDRANT_COLLECTION_NAME
        
        self.mongo_client = AsyncIOMotorClient(self.mongodb_url)
        self.db = self.mongo_client[self.db_name]
        self.qdrant_client = QdrantClient(url=self.qdrant_url, api_key=self.qdrant_api_key)

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
        collections = ["files", "metadata_types", "file_toc_trees"]
        
        for coll_name in collections:
            docs = await self.db[coll_name].find({}).to_list(None)
            docs = json_serializable(docs)
            for doc in docs:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
            snapshot_mongodb[coll_name] = docs
            logger.info(f"    ✓ Exported {len(docs)} documents from {coll_name}")
        
        # 2. Export Qdrant
        logger.info(f"  Exporting Qdrant points from {self.collection_name}...")
        points = []
        offset = None
        while True:
            response, next_offset = self.qdrant_client.scroll(
                collection_name=self.collection_name,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=True
            )
            for p in response:
                points.append({
                    "id": p.id,
                    "vector": p.vector,
                    "payload": p.payload
                })
            
            offset = next_offset
            if offset is None:
                break
        
        snapshot = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "document_count": len(snapshot_mongodb.get("files", [])),
                "qdrant_points_count": len(points)
            },
            "mongodb": snapshot_mongodb,
            "qdrant": points
        }
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
            
        logger.info(f"✅ Export complete! {snapshot['metadata']['document_count']} files, {len(points)} vector points.")

    async def import_data(self, input_path: str):
        if not os.path.exists(input_path):
            logger.error(f"❌ Snapshot file not found: {input_path}")
            return

        logger.info(f"🚀 Importing RAG snapshot from {input_path}...")
        with open(input_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
            
        # 1. Import MongoDB
        from bson import ObjectId
        logger.info("  Restoring MongoDB collections...")
        for coll_name, docs in snapshot.get("mongodb", {}).items():
            if docs:
                # Convert string IDs back to ObjectId
                for d in docs:
                    if "_id" in d and isinstance(d["_id"], str):
                        try:
                            d["_id"] = ObjectId(d["_id"])
                        except:
                            pass
                
                await self.db[coll_name].insert_many(docs)
                logger.info(f"    ✓ Restored {len(docs)} documents to {coll_name}")

        # 2. Import Qdrant
        logger.info(f"  Restoring Qdrant points to {self.collection_name}...")
        points_data = snapshot["qdrant"]
        if points_data:
            from qdrant_client.http import models as qm
            
            qdrant_points = []
            for p in points_data:
                qdrant_points.append(qm.PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p["payload"]
                ))
            
            # Ensure collection exists
            collections = self.qdrant_client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                self.qdrant_client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qm.VectorParams(
                        size=settings.QDRANT_VECTOR_SIZE,
                        distance=qm.Distance.COSINE
                    )
                )

            # Upsert in batches to avoid timeouts
            batch_size = 20
            for i in range(0, len(qdrant_points), batch_size):
                batch = qdrant_points[i:i + batch_size]
                self.qdrant_client.upsert(
                    collection_name=self.collection_name,
                    points=batch,
                    wait=True
                )
                logger.info(f"  ✓ Restored batch {i//batch_size + 1}/{(len(qdrant_points)-1)//batch_size + 1}")
            
            logger.info(f"  ✓ Restored {len(qdrant_points)} vector points")
            
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
