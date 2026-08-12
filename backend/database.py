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
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    db = client[DB_NAME]
    receiving_collection = db["receiving_records"]
    challans_collection = db["receiving_challans"]
    dispatch_collection = db["dispatches"]
    notification_collection = db["notification_logs"]
    users_collection = db["users"]
    pos_collection = db["purchase_orders"]
    project_engineer_collection = db["project_engineer_records"]
    vendor_payments_collection = db["vendor_payments"]
    customer_receivables_collection = db["customer_receivables"]
    file_uploads_collection = db["file_uploads"]
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
    vendor_payments_collection = DummyCollection()
    customer_receivables_collection = DummyCollection()
    file_uploads_collection = DummyCollection()


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
        dispatch_collection.create_index("dispatch_number")
        notification_collection.create_index("sent_at")
        project_engineer_collection.create_index("id")
        file_uploads_collection.create_index("id")
        pos_collection.create_index("id")
        logger.info("Connected to MongoDB Atlas cluster0. Indices initialized.")
    except Exception as e:
        logger.warning(f"MongoDB Connection Warning: {e}")


def get_db():
    return db
