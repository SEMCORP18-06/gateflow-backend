import json
import os
import tempfile
from datetime import datetime

if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    DATA_DIR = os.path.join(tempfile.gettempdir(), "gateflow_data")
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = os.path.join(tempfile.gettempdir(), "gateflow_data")
    os.makedirs(DATA_DIR, exist_ok=True)


def _get_mongo_collection(name: str):
    """Safely retrieves PyMongo collection for cloud database persistence."""
    try:
        from backend.database import get_db
        db = get_db()
        if db is not None:
            return db[name]
    except Exception:
        pass
    return None


class PersistentStore:
    def __init__(self, name: str, seed_list=None):
        self.name = name
        self.file_path = os.path.join(DATA_DIR, f"{name}.json")
        self.data = {}
        self.load(seed_list)

    def load(self, seed_list=None):
        # 1. Try loading from MongoDB Atlas first (Cloud Persistent Store)
        col = _get_mongo_collection(self.name)
        if col is not None:
            try:
                docs = list(col.find({}))
                if docs:
                    self.data = {}
                    for d in docs:
                        did = str(d.get("id") or d.get("_id") or "")
                        if did:
                            d["id"] = did
                            if "_id" in d:
                                del d["_id"]
                            self.data[did] = d
                    self.save_local()
                    return
            except Exception as e:
                print(f"MongoDB load warning for {self.name}: {e}")

        # 2. Fallback to local JSON file
        pkg_data_file = os.path.join(os.path.dirname(__file__), "data", f"{self.name}.json")
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                return
            except Exception as e:
                print(f"Error loading {self.file_path}: {e}")

        # 3. Fallback to package seed file
        if os.path.exists(pkg_data_file):
            try:
                with open(pkg_data_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                return
            except Exception as e:
                print(f"Error loading package data {pkg_data_file}: {e}")

        self.data = {}
        if seed_list:
            for item in seed_list:
                item_id = item.get("id") or item.get("_id") or f"id_{len(self.data)+1}"
                item["id"] = str(item_id)
                self.data[str(item_id)] = item
        self.save_local()

    def save_local(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Unable to write to {self.file_path}: {e}")

    def save(self):
        self.save_local()

    def get_all(self, sort_key="created_at", reverse=True):
        col = _get_mongo_collection(self.name)
        if col is not None:
            try:
                docs = list(col.find({}))
                if docs:
                    new_data = {}
                    for d in docs:
                        did = str(d.get("id") or d.get("_id") or "")
                        if did:
                            d["id"] = did
                            if "_id" in d:
                                del d["_id"]
                            new_data[did] = d
                    self.data = new_data
                    self.save_local()
            except Exception:
                pass

        items = list(self.data.values())
        if sort_key:
            items.sort(key=lambda x: str(x.get(sort_key, "")), reverse=reverse)
        return items

    def get(self, item_id: str):
        sid = str(item_id)
        if sid in self.data:
            return self.data[sid]

        for k, v in self.data.items():
            if (v.get("id") == sid or 
                v.get("invoice_number") == sid or 
                v.get("challan_number") == sid or 
                v.get("po_number") == sid):
                return v

        col = _get_mongo_collection(self.name)
        if col is not None:
            try:
                from bson import ObjectId
                q = [{"id": sid}, {"_id": sid}, {"invoice_number": sid}, {"challan_number": sid}, {"po_number": sid}]
                if ObjectId.is_valid(sid):
                    q.append({"_id": ObjectId(sid)})
                doc = col.find_one({"$or": q})
                if doc:
                    did = str(doc.get("id") or doc.get("_id") or sid)
                    doc["id"] = did
                    if "_id" in doc:
                        del doc["_id"]
                    self.data[did] = doc
                    return doc
            except Exception:
                pass
        return None

    def insert(self, item_id: str, item: dict):
        sid = str(item_id)
        item["id"] = sid
        if "created_at" not in item:
            item["created_at"] = datetime.now().isoformat()

        item_copy = dict(item)
        if "_id" in item_copy:
            del item_copy["_id"]

        self.data[sid] = item_copy
        self.save_local()

        col = _get_mongo_collection(self.name)
        if col is not None:
            try:
                col.replace_one({"id": sid}, dict(item_copy), upsert=True)
            except Exception as e:
                print(f"MongoDB insert error for {self.name}: {e}")

        return item_copy

    def update(self, item_id: str, updates: dict):
        sid = str(item_id)
        if sid in self.data:
            self.data[sid].update(updates)
            item_copy = dict(self.data[sid])
            if "_id" in item_copy:
                del item_copy["_id"]
            self.data[sid] = item_copy
            self.save_local()

            col = _get_mongo_collection(self.name)
            if col is not None:
                try:
                    col.update_one({"id": sid}, {"$set": updates}, upsert=True)
                except Exception as e:
                    print(f"MongoDB update error for {self.name}: {e}")

            return item_copy
        return None

    def delete(self, item_id: str):
        sid = str(item_id)
        keys_to_del = []
        for k, v in self.data.items():
            if (k == sid or 
                v.get("id") == sid or 
                v.get("invoice_number") == sid or 
                v.get("challan_number") == sid or 
                v.get("po_number") == sid):
                keys_to_del.append(k)

        for k in keys_to_del:
            if k in self.data:
                del self.data[k]
        self.save_local()

        col = _get_mongo_collection(self.name)
        if col is not None:
            try:
                from bson import ObjectId
                q = [{"id": sid}, {"_id": sid}, {"invoice_number": sid}, {"challan_number": sid}, {"po_number": sid}]
                if ObjectId.is_valid(sid):
                    q.append({"_id": ObjectId(sid)})
                col.delete_many({"$or": q})
            except Exception as e:
                print(f"MongoDB delete error for {self.name}: {e}")

        return True


# Initialize Persistent Stores for GateFlow Modules
receiving_store = PersistentStore("receiving_records", [])
challans_store = PersistentStore("receiving_challans", [])
dispatch_store = PersistentStore("dispatches", [])
notifications_store = PersistentStore("notification_logs", [])
pos_store = PersistentStore("purchase_orders", [])
project_engineer_store = PersistentStore("project_engineer_records", [])
vendor_payments_store = PersistentStore("vendor_payments", [])
customer_receivables_store = PersistentStore("customer_receivables", [])
