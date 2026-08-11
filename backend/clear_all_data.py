import os
import json
from backend.database import (
    receiving_collection, challans_collection, dispatch_collection,
    notification_collection, pos_collection, project_engineer_collection
)
from backend.persistent_store import (
    receiving_store, challans_store, dispatch_store, notifications_store,
    pos_store, project_engineer_store, vendor_payments_store, customer_receivables_store
)

def wipe_data():
    print("=== Wiping All Dummy Records from Persistent Storage & Databases ===")

    # Clear memory stores
    stores = [
        receiving_store, challans_store, dispatch_store, notifications_store,
        pos_store, project_engineer_store, vendor_payments_store, customer_receivables_store
    ]
    for s in stores:
        s.data = {}
        s.save()
        print(f"Cleared JSON store: {s.file_path}")

    # Clear MongoDB collections if available
    try:
        receiving_collection.delete_many({})
        challans_collection.delete_many({})
        dispatch_collection.delete_many({})
        notification_collection.delete_many({})
        pos_collection.delete_many({})
        project_engineer_collection.delete_many({})
        print("Cleared MongoDB collections.")
    except Exception as e:
        print(f"MongoDB Wipe Notice: {e}")

    print("=== All Dummy Records Successfully Removed! ===")

if __name__ == "__main__":
    wipe_data()
