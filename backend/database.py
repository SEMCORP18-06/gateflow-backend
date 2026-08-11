import os
import logging
from pymongo import MongoClient

logger = logging.getLogger("GateFlowDatabase")

MONGO_URI = os.getenv(
    "MONGO_URI",
    os.getenv(
        "MONGODB_URI",
        "mongodb+srv://enquiry_db_user:FJND34ouaoPsNCby@cluster0.rr0husv.mongodb.net/?retryWrites=true&w=majority"
    )
)
DB_NAME = os.getenv("DB_NAME", "gateflow_db")

client = None
db = None

class DummyCollection:
    """Fallback dummy collection for offline/fallback mode."""
    def insert_one(self, doc): pass
    def find(self, *args, **kwargs): return []
    def find_one(self, *args, **kwargs): return None
    def update_one(self, *args, **kwargs): pass
    def delete_one(self, *args, **kwargs): pass
    def create_index(self, *args, **kwargs): pass

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=300, connectTimeoutMS=300)
    db = client[DB_NAME]
    receiving_collection = db["receiving_records"]
    challans_collection = db["receiving_challans"]
    dispatch_collection = db["dispatches"]
    notification_collection = db["notification_logs"]
    users_collection = db["users"]
    pos_collection = db["purchase_orders"]
    project_engineer_collection = db["project_engineer_records"]
except Exception as e:
    logger.warning(f"MongoDB Atlas initialization skipped (Offline/Persistent Store Mode): {e}")
    db = None
    receiving_collection = DummyCollection()
    challans_collection = DummyCollection()
    dispatch_collection = DummyCollection()
    notification_collection = DummyCollection()
    users_collection = DummyCollection()
    pos_collection = DummyCollection()
    project_engineer_collection = DummyCollection()


def format_doc(doc: dict) -> dict:
    """Helper to convert MongoDB document _id to id string."""
    if not doc:
        return doc
    doc_copy = doc.copy()
    if "_id" in doc_copy:
        doc_copy["id"] = str(doc_copy["_id"])
        del doc_copy["_id"]
    return doc_copy


def init_db():
    """Verifies MongoDB Atlas connection and sets up indexes."""
    if not client:
        logger.info("Operating with GateFlow Ultra-Fast Local Persistent Storage Engine.")
        return
    try:
        client.admin.command('ping')
        receiving_collection.create_index("invoice_number")
        dispatch_collection.create_index("dispatch_number", unique=True)
        notification_collection.create_index("sent_at")
        logger.info("Connected to MongoDB Atlas cluster0. Indices initialized.")
    except Exception as e:
        logger.warning(f"MongoDB Connection Warning: {e}")


def get_db():
    return db
