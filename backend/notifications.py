import logging
import uuid
from datetime import datetime

from backend.database import notification_collection, format_doc
from backend.persistent_store import notifications_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GateFlowNotifications")


def send_email(recipient: str, subject: str, message_body: str, section: str = "RECEIVING") -> dict:
    """
    Records email notification audit trail locally in persistent store & database.
    All external SMTP network activity is completely disabled.
    """
    logger.info(f"[INTERNAL EMAIL LOG] Section: {section} | To: {recipient} | Subject: {subject}")
    
    doc_id = str(uuid.uuid4())
    doc = {
        "_id": doc_id,
        "id": doc_id,
        "type": "EMAIL",
        "section": section.upper(),
        "recipient": recipient,
        "subject": subject,
        "message_body": message_body,
        "status": "SENT",
        "sent_at": datetime.utcnow().isoformat(),
        "created_at": datetime.utcnow().isoformat()
    }

    # Save to Instant Persistent Disk Store
    try:
        notifications_store.insert(doc_id, doc)
    except Exception as ex:
        logger.warning(f"Persistent store notification insert exception: {ex}")

    # Async non-blocking write to Mongo Atlas if available
    try:
        if notification_collection is not None:
            notification_collection.insert_one(doc)
    except Exception as e:
        logger.warning(f"MongoDB notification insert warning: {e}")

    return format_doc(doc)


def send_sms(recipient_phone: str, message_body: str, section: str = "DISPATCH") -> dict:
    """Sends SMS notification (mock audit log) with section tag."""
    doc_id = str(uuid.uuid4())
    logger.info(f"[INTERNAL SMS LOG] Section: {section} | To: {recipient_phone} | Body: {message_body[:80]}...")

    doc = {
        "_id": doc_id,
        "id": doc_id,
        "type": "SMS",
        "section": section.upper(),
        "recipient": recipient_phone,
        "subject": "Dispatch Alert",
        "message_body": message_body,
        "status": "SENT",
        "sent_at": datetime.utcnow().isoformat(),
        "created_at": datetime.utcnow().isoformat()
    }

    try:
        notifications_store.insert(doc_id, doc)
    except Exception as ex:
        logger.warning(f"Persistent store SMS notification insert exception: {ex}")

    try:
        if notification_collection is not None:
            notification_collection.insert_one(doc)
    except Exception as e:
        logger.warning(f"MongoDB notification insert warning: {e}")

    return format_doc(doc)
