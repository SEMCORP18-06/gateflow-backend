import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

class PersistentStore:
    def __init__(self, name: str, seed_list=None):
        self.file_path = os.path.join(DATA_DIR, f"{name}.json")
        self.data = {}
        self.load(seed_list)

    def load(self, seed_list=None):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                return
            except Exception as e:
                print(f"Error loading {self.file_path}: {e}")
        
        self.data = {}
        if seed_list:
            for item in seed_list:
                item_id = item.get("id") or item.get("_id") or f"id_{len(self.data)+1}"
                item["id"] = item_id
                self.data[item_id] = item
        self.save()

    def save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving {self.file_path}: {e}")

    def get_all(self, sort_key="created_at", reverse=True):
        items = list(self.data.values())
        if sort_key:
            items.sort(key=lambda x: str(x.get(sort_key, "")), reverse=reverse)
        return items

    def get(self, item_id: str):
        return self.data.get(str(item_id))

    def insert(self, item_id: str, item: dict):
        item["id"] = str(item_id)
        if "created_at" not in item:
            item["created_at"] = datetime.now().isoformat()
        self.data[str(item_id)] = item
        self.save()
        return item

    def update(self, item_id: str, updates: dict):
        sid = str(item_id)
        if sid in self.data:
            self.data[sid].update(updates)
            self.save()
            return self.data[sid]
        return None

    def delete(self, item_id: str):
        sid = str(item_id)
        if sid in self.data:
            del self.data[sid]
            self.save()
            return True
        return False


# Initialize Persistent Stores for GateFlow Modules (Clean Production State)
receiving_store = PersistentStore("receiving_records", [])
challans_store = PersistentStore("receiving_challans", [])
dispatch_store = PersistentStore("dispatches", [])
notifications_store = PersistentStore("notification_logs", [])
pos_store = PersistentStore("purchase_orders", [])
project_engineer_store = PersistentStore("project_engineer_records", [])
vendor_payments_store = PersistentStore("vendor_payments", [])
customer_receivables_store = PersistentStore("customer_receivables", [])
