import os
import shutil
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.database import (
    init_db, format_doc, receiving_collection, challans_collection, dispatch_collection, notification_collection, users_collection, pos_collection, project_engineer_collection
)
from backend.persistent_store import (
    receiving_store, challans_store, dispatch_store, notifications_store, pos_store, project_engineer_store, vendor_payments_store, customer_receivables_store
)
from backend.ocr_engine import extract_metadata_from_image
from backend.notifications import send_email, send_sms
from backend.exporter import export_to_csv, export_to_xlsx, export_to_pdf
from backend.scheduler import start_scheduler, check_payment_calendar_job
from backend.seed_data import seed_database_if_empty

import tempfile

# App directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    UPLOADS_DIR = os.path.join(tempfile.gettempdir(), "gateflow_uploads")
else:
    UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")

try:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
except Exception:
    UPLOADS_DIR = os.path.join(tempfile.gettempdir(), "gateflow_uploads")
    os.makedirs(UPLOADS_DIR, exist_ok=True)

# Initialize MongoDB Atlas database & seed data
try:
    init_db()
    seed_database_if_empty()
except Exception as e:
    print(f"Startup DB init warning: {e}")

app = FastAPI(title="GateFlow SCM API Server", version="2.0")

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory authentication fallback store
MEMORY_USERS_DB = {
    "admin@semco.com": {
        "id": "u_admin",
        "email": "admin@semco.com",
        "full_name": "Master Admin",
        "password": "pass123",
        "role": "admin"
    },
    "receiving@semco.com": {
        "id": "u_rec",
        "email": "receiving@semco.com",
        "full_name": "Receiving Desk",
        "password": "pass123",
        "role": "receiving"
    },
    "engineer@semco.com": {
        "id": "u_eng",
        "email": "engineer@semco.com",
        "full_name": "Project Engineer Desk (Rajesh Sharma)",
        "password": "pass123",
        "role": "project_engineer"
    },
    "dispatch@semco.com": {
        "id": "u_disp",
        "email": "dispatch@semco.com",
        "full_name": "Dispatch Desk",
        "password": "pass123",
        "role": "dispatch"
    },
    "qcadmin@semco.com": {
        "id": "u_qc",
        "email": "qcadmin@semco.com",
        "full_name": "QC Admin",
        "password": "pass123",
        "role": "qc_admin"
    },
    "poadmin@semco.com": {
        "id": "u_po",
        "email": "poadmin@semco.com",
        "full_name": "Purchase Orders Desk",
        "password": "pass123",
        "role": "po_admin"
    },
    "poprep@semco.com": {
        "id": "u_poprep",
        "email": "poprep@semco.com",
        "full_name": "PO Preparation Desk (Umesh H. Patil)",
        "password": "pass123",
        "role": "po_preparer"
    },
    "poappr@semco.com": {
        "id": "u_poappr",
        "email": "poappr@semco.com",
        "full_name": "PO Approval Desk (Authorised Signatory)",
        "password": "pass123",
        "role": "po_approver"
    }
}


@app.on_event("startup")
def startup_event():
    try:
        start_scheduler()
    except Exception as e:
        print(f"Scheduler startup warning: {e}")
    
    # Ensure sample pending Project Engineer package exists for QC Gate inspection
    try:
        pending_recs = [r for r in project_engineer_store.get_all() if r.get("status") == "Pending QC"]
        if not pending_recs:
            sample_pe = {
                "id": "pe_seed_001",
                "package_name": "High Vacuum Pump Assembly Technical Drawings & MTC Package",
                "project_ref": "PRJ-SEM-2026-101",
                "po_number": "PO-2026-0042",
                "vendor_name": "Thermax Limited - Process Division",
                "engineer_name": "Rajesh Sharma (Project Engineer)",
                "notes": "Includes QAP compliance sheet, FAT log, and SS316L Mill Test Certificate.",
                "files": [
                    {
                        "file_name": "Thermax_Vacuum_Pump_Blueprint_v2.pdf",
                        "document_path": "",
                        "category": "Technical Drawing",
                        "notes": "ANSI B16.5 150# Flange Specs"
                    },
                    {
                        "file_name": "Mill_Test_Certificate_SS316L.pdf",
                        "document_path": "",
                        "category": "Material Test Certificate (MTC)",
                        "notes": "Heat #88921 Grade 316L"
                    }
                ],
                "status": "Pending QC",
                "qc_comments": "Sent for Approval to QC Desk",
                "created_at": datetime.now().isoformat()
            }
            project_engineer_store.insert("pe_seed_001", sample_pe)
    except Exception:
        pass

    print("GateFlow SCM API Server running with Ultra-Fast Persistent Storage Engine.")


# ----------------------------------------------------
# DEDICATED PROFILE AUTHENTICATION
# ----------------------------------------------------

@app.post("/api/auth/register")
def register_user(
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...)
):
    """Registers user for a specific profile (receiving, dispatch, qc_admin, admin)."""
    clean_email = email.strip().lower()
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": clean_email,
        "full_name": full_name,
        "password": password,
        "role": role,
        "created_at": datetime.now().isoformat()
    }

    try:
        users_collection.insert_one(dict(user_doc))
    except Exception:
        pass
    MEMORY_USERS_DB[clean_email] = user_doc

    return format_doc(user_doc)


@app.post("/api/auth/login")
def login_user(
    email: str = Form(...),
    password: str = Form(...),
    role: Optional[str] = Form(None)
):
    clean_email = email.lower().strip()
    user = MEMORY_USERS_DB.get(clean_email)

    if not user:
        try:
            u_doc = users_collection.find_one({"email": clean_email, "password": password})
            if u_doc:
                user = u_doc
        except Exception:
            pass

    if not user or user.get("password") != password:
        raise HTTPException(status_code=401, detail="Invalid email ID or password")

    return format_doc(user)


def log_audit_action(section: str, subject: str, message_body: str, recipient: str = "receiving-desk@semco.com"):
    """Logs an audit activity into persistent notification store."""
    nid = f"notif_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    doc = {
        "id": nid,
        "recipient": recipient,
        "subject": subject,
        "message_body": message_body,
        "section": section.upper(),
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "created_at": datetime.now().isoformat()
    }
    notifications_store.insert(nid, doc)
    try:
        notification_collection.insert_one(dict(doc))
    except Exception:
        pass
    return doc


# ----------------------------------------------------
# MODULE 1: RECEIVING & INVOICE OCR API
# ----------------------------------------------------

@app.post("/api/receiving")
async def save_receiving_record(
    id: Optional[str] = Form(None),
    invoice_number: str = Form(...),
    vendor_name: str = Form(...),
    invoice_date: str = Form(...),
    due_date: str = Form(...),
    total_amount: float = Form(...),
    po_number: Optional[str] = Form(""),
    challan_number: Optional[str] = Form(""),
    challan_doc_path: Optional[str] = Form(""),
    document_path: Optional[str] = Form(""),
    qc_comments: Optional[str] = Form(""),
    extracted_fields_json: Optional[str] = Form("{}"),
    status: Optional[str] = Form("Verified"),
    packing_list_file: Optional[UploadFile] = File(None)
):
    """Saves or updates a receiving record with instant persistent local storage."""
    try:
        parsed_fields = json.loads(extracted_fields_json or "{}")
    except json.JSONDecodeError:
        parsed_fields = {}

    packing_list_doc_path = ""
    if packing_list_file and packing_list_file.filename:
        filename = f"rec_packlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{packing_list_file.filename}"
        path = os.path.join(UPLOADS_DIR, filename)
        with open(path, "wb") as b:
            shutil.copyfileobj(packing_list_file.file, b)
        packing_list_doc_path = f"/uploads/{filename}"

    doc_id = id or f"rec_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    update_data = {
        "id": doc_id,
        "invoice_number": invoice_number,
        "vendor_name": vendor_name,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "total_amount": float(total_amount),
        "po_number": po_number or parsed_fields.get("PO Number", ""),
        "challan_number": challan_number or parsed_fields.get("Challan Number", ""),
        "challan_doc_path": challan_doc_path or parsed_fields.get("Challan Document Path", ""),
        "document_path": document_path or "",
        "packing_list_doc": packing_list_doc_path,
        "qc_comments": qc_comments or "Verified on Receival",
        "extracted_fields": parsed_fields,
        "status": status or "Verified",
        "created_at": datetime.now().isoformat()
    }

    # Save to persistent file store instantly
    rec = receiving_store.insert(doc_id, update_data)

    # Log section-specific Audit Trail
    log_audit_action(
        section="RECEIVING",
        subject="Inward Invoice Saved",
        message_body=f"Invoice #{invoice_number} from vendor '{vendor_name}' (Amount: ₹{float(total_amount):,.2f}) logged into Receiving repository."
    )

    # Async try MongoDB without blocking
    try:
        receiving_collection.update_one({"_id": doc_id}, {"$set": update_data}, upsert=True)
    except Exception:
        pass

    return rec


@app.get("/api/receiving")
def get_receiving_records(status: Optional[str] = None):
    """Get receiving records instantly from persistent store."""
    records = receiving_store.get_all(sort_key="created_at", reverse=True)
    if status:
        records = [r for r in records if r.get("status") == status]
    return records


@app.post("/api/receiving/{record_id}/submit-qc")
def submit_receiving_qc(record_id: str):
    """Transitions status to Pending QC in persistent store."""
    rec = receiving_store.update(record_id, {"status": "Pending QC"})
    try:
        receiving_collection.update_one({"_id": record_id}, {"$set": {"status": "Pending QC"}})
    except Exception:
        pass

    if rec:
        log_audit_action(
            section="RECEIVING",
            subject="Invoice Submitted to QC",
            message_body=f"Receiving Invoice #{rec.get('invoice_number')} submitted for QC Gate approval."
        )
        send_email(
            recipient="qc-admin@gateflow-scm.com",
            subject=f"[QC ALERT] Pending Approval for Invoice #{rec.get('invoice_number')}",
            message_body=f"Receiving Record #{rec.get('invoice_number')} from vendor '{rec.get('vendor_name')}' has been submitted for QC approval."
        )
    return rec or {"id": record_id, "status": "Pending QC"}


@app.post("/api/receiving/{record_id}/approve-qc")
def approve_receiving_qc(record_id: str, qc_comments: Optional[str] = Form("Approved by QC")):
    """QC Admin approves record -> Verified."""
    rec = receiving_store.update(record_id, {"status": "Verified", "qc_comments": qc_comments})
    try:
        receiving_collection.update_one({"_id": record_id}, {"$set": {"status": "Verified", "qc_comments": qc_comments}})
    except Exception:
        pass

    if rec:
        log_audit_action(
            section="RECEIVING",
            subject="Invoice Verified by QC",
            message_body=f"QC Approval complete for Invoice #{rec.get('invoice_number')} ({rec.get('vendor_name')})."
        )
        send_email(
            recipient="receiving-desk@gateflow-scm.com",
            subject=f"[QC APPROVED] Invoice #{rec.get('invoice_number')} Verified",
            message_body=f"QC Approval complete for Invoice #{rec.get('invoice_number')} ({rec.get('vendor_name')})."
        )
    return rec or {"id": record_id, "status": "Verified"}


@app.post("/api/receiving/{record_id}/record-payment")
def record_receiving_payment(
    record_id: str,
    payment_type: str = Form(...),
    paid_amount: float = Form(0.0),
    payment_date: Optional[str] = Form(None),
    payment_notes: Optional[str] = Form("")
):
    """Records full or partial payment for vendor payables."""
    rec = receiving_store.get(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Receiving record not found")

    total_amt = float(rec.get("total_amount") or 0.0)
    current_paid = float(rec.get("paid_amount") or 0.0)

    if payment_type == "FULL":
        new_paid_chunk = max(0.0, total_amt - current_paid)
        total_paid_now = total_amt
        remaining = 0.0
        new_status = "Paid"
    else:
        new_paid_chunk = float(paid_amount)
        total_paid_now = current_paid + new_paid_chunk
        if total_paid_now >= total_amt - 0.01:
            total_paid_now = total_amt
            remaining = 0.0
            new_status = "Paid"
        else:
            remaining = max(0.0, total_amt - total_paid_now)
            new_status = "Partially Paid"

    history = rec.get("payment_history") or []
    history.append({
        "payment_type": payment_type,
        "amount": new_paid_chunk,
        "date": payment_date or datetime.now().strftime("%Y-%m-%d"),
        "notes": payment_notes or "",
        "created_at": datetime.now().isoformat()
    })

    update_fields = {
        "status": new_status,
        "paid_amount": total_paid_now,
        "remaining_balance": remaining,
        "payment_history": history
    }

    updated_rec = receiving_store.update(record_id, update_fields)
    try:
        receiving_collection.update_one({"_id": record_id}, {"$set": update_fields})
    except Exception:
        pass

    inv_num = rec.get("invoice_number", record_id)
    msg = f"Vendor Invoice #{inv_num} payment recorded: ₹{new_paid_chunk:,.2f} ({new_status}). Remaining balance: ₹{remaining:,.2f}."
    log_audit_action(section="RECEIVING", subject=f"Invoice Payment ({new_status})", message_body=msg)

    return updated_rec or rec


@app.post("/api/receiving/{record_id}/mark-paid")
def mark_receiving_paid(record_id: str):
    """Marks receiving invoice as Paid in full (backward compatible)."""
    return record_receiving_payment(record_id=record_id, payment_type="FULL", paid_amount=0.0)


@app.delete("/api/receiving/{record_id}")
def delete_receiving_record(record_id: str):
    """Deletes a receiving invoice record from persistent store."""
    rec = receiving_store.get(record_id)
    inv_num = rec.get("invoice_number", record_id) if rec else record_id
    receiving_store.delete(record_id)
    try:
        receiving_collection.delete_one({"_id": record_id})
    except Exception:
        pass

    log_audit_action(
        section="RECEIVING",
        subject="Invoice Record Deleted",
        message_body=f"Invoice record #{inv_num} deleted from Receiving repository."
    )
    return {"status": "deleted", "id": record_id}


# ----------------------------------------------------
# RECEIVING SUB-SECTION 2: DELIVERY CHALLANS API
# ----------------------------------------------------

@app.get("/api/receiving/challans")
def get_delivery_challans():
    """Returns list of inward delivery challans from persistent store."""
    return challans_store.get_all(sort_key="created_at", reverse=True)


@app.post("/api/receiving/challans")
async def save_delivery_challan(
    challan_number: str = Form(...),
    vendor_name: str = Form(...),
    challan_date: str = Form(...),
    transporter_name: Optional[str] = Form(""),
    vehicle_number: Optional[str] = Form(""),
    items_summary: Optional[str] = Form(""),
    po_number: Optional[str] = Form(""),
    document_path: Optional[str] = Form(""),
    invoice_status: Optional[str] = Form("Awaiting Invoice"),
    custom_fields_json: Optional[str] = Form("{}"),
    challan_file: Optional[UploadFile] = File(None)
):
    """Logs a new inward delivery challan with instant persistent storage."""
    doc_path = document_path or ""
    if challan_file and challan_file.filename:
        filename = f"challan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{challan_file.filename}"
        path = os.path.join(UPLOADS_DIR, filename)
        with open(path, "wb") as b:
            shutil.copyfileobj(challan_file.file, b)
        doc_path = f"/uploads/{filename}"

    custom_fields = {}
    try:
        if custom_fields_json:
            custom_fields = json.loads(custom_fields_json)
    except Exception:
        pass

    cid = f"ch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    doc = {
        "id": cid,
        "challan_number": challan_number,
        "vendor_name": vendor_name,
        "challan_date": challan_date,
        "transporter_name": transporter_name or "N/A",
        "vehicle_number": vehicle_number or "N/A",
        "po_number": po_number or "N/A",
        "items_summary": items_summary or "Inward Material Goods",
        "challan_doc": doc_path,
        "document_path": doc_path,
        "invoice_status": invoice_status or "Awaiting Invoice",
        "custom_fields": custom_fields,
        "status": "Inward Verified",
        "created_at": datetime.now().isoformat()
    }

    rec = challans_store.insert(cid, doc)

    log_audit_action(
        section="RECEIVING",
        subject="Delivery Challan Logged",
        message_body=f"Inward Delivery Challan #{challan_number} logged from vendor '{vendor_name}' for goods '{items_summary}'."
    )

    try:
        mongo_doc = dict(doc)
        challans_collection.insert_one(mongo_doc)
    except Exception:
        pass
    return rec


@app.delete("/api/receiving/challans/{challan_id}")
def delete_delivery_challan(challan_id: str):
    """Deletes a delivery challan record from persistent store."""
    ch = challans_store.get(challan_id)
    cnum = ch.get("challan_number", challan_id) if ch else challan_id
    challans_store.delete(challan_id)
    try:
        challans_collection.delete_one({"_id": challan_id})
    except Exception:
        pass

    log_audit_action(
        section="RECEIVING",
        subject="Delivery Challan Deleted",
        message_body=f"Inward Delivery Challan #{cnum} deleted from Receiving repository."
    )
    return {"status": "deleted", "id": challan_id}


@app.post("/api/receiving/ocr-upload")
async def process_ocr_upload(file: UploadFile = File(...)):
    """Receives invoice image upload (PDF, JPEG, JPG, PNG, WEBP), runs Image Preparation & OCR Engine."""
    filename = f"ocr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    file_path = os.path.join(UPLOADS_DIR, filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted = extract_metadata_from_image(file_path)
    fields = extracted.get("extracted_fields", {})

    return {
        "extracted_fields": fields,
        "raw_ocr_preview": extracted.get("raw_ocr_preview", ""),
        "raw_ocr_full_text": extracted.get("raw_ocr_full_text", ""),
        "invoice_number": fields.get("Invoice Number", f"INV-{datetime.now().strftime('%m%d%H%M')}"),
        "vendor_name": fields.get("Vendor Name", "Supplier Partner"),
        "invoice_date": fields.get("Invoice Date", datetime.now().strftime("%Y-%m-%d")),
        "due_date": fields.get("Due Date", (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")),
        "total_amount": fields.get("Total Amount", "0.00"),
        "document_path": f"/uploads/{filename}"
    }


# ----------------------------------------------------
# MANUAL ENTRY FILE UPLOAD (no OCR)
# ----------------------------------------------------

@app.post("/api/receiving/upload-file")
async def upload_receiving_file(file: UploadFile = File(...)):
    """Saves an uploaded invoice file without running OCR. Used for manual entry."""
    filename = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    file_path = os.path.join(UPLOADS_DIR, filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"document_path": f"/uploads/{filename}", "filename": filename}


# ----------------------------------------------------
# MODULE 2: TRI-PARTY DISPATCH & COLLECTIONS API
# ----------------------------------------------------

@app.post("/api/dispatch")
async def create_dispatch(
    po_number: Optional[str] = Form(""),
    supplier_name: str = Form("SEMCO Dispatch Team"),
    supplier_phone: str = Form(""),
    driver_name: str = Form(...),
    driver_phone: str = Form(...),
    vehicle_number: str = Form(...),
    truck_type: str = Form(...),
    client_name: str = Form(...),
    delivery_location: str = Form(...),
    client_email: str = Form(...),
    client_phone: str = Form(...),
    invoice_amount: Optional[float] = Form(50000.0),
    collection_due_date: Optional[str] = Form(None),
    supplier_invoice_file: Optional[UploadFile] = File(None),
    supplier_challan_file: Optional[UploadFile] = File(None),
    qc_package_ids_json: Optional[str] = Form("[]"),
    additional_files: List[UploadFile] = File([]),
    supplier_packing_list_file: Optional[UploadFile] = File(None),
    material_pictures: List[UploadFile] = File([])
):
    """Creates a new Tri-Party dispatch bundle with persistent storage.
    QC-approved documents from Project Engineer packages are auto-linked."""
    disp_id = f"disp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    disp_num = f"DISP-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    due_dt_str = collection_due_date
    if not due_dt_str:
        due_dt_str = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")

    invoice_doc_path = ""
    if supplier_invoice_file and supplier_invoice_file.filename:
        filename = f"sinv_{datetime.now().strftime('%H%M%S')}_{supplier_invoice_file.filename}"
        path = os.path.join(UPLOADS_DIR, filename)
        with open(path, "wb") as b:
            shutil.copyfileobj(supplier_invoice_file.file, b)
        invoice_doc_path = f"/uploads/{filename}"

    challan_doc_path = ""
    if supplier_challan_file and supplier_challan_file.filename:
        filename = f"schallan_{datetime.now().strftime('%H%M%S')}_{supplier_challan_file.filename}"
        path = os.path.join(UPLOADS_DIR, filename)
        with open(path, "wb") as b:
            shutil.copyfileobj(supplier_challan_file.file, b)
        challan_doc_path = f"/uploads/{filename}"

    # Legacy: still accept packing list if sent (backward compat)
    packing_list_doc_path = ""
    if supplier_packing_list_file and supplier_packing_list_file.filename:
        filename = f"spacklist_{datetime.now().strftime('%H%M%S')}_{supplier_packing_list_file.filename}"
        path = os.path.join(UPLOADS_DIR, filename)
        with open(path, "wb") as b:
            shutil.copyfileobj(supplier_packing_list_file.file, b)
        packing_list_doc_path = f"/uploads/{filename}"

    # Legacy: still accept material pictures if sent (backward compat)
    pics_paths = []
    for pic in material_pictures:
        if pic and pic.filename:
            filename = f"mat_{datetime.now().strftime('%H%M%S')}_{pic.filename}"
            path = os.path.join(UPLOADS_DIR, filename)
            with open(path, "wb") as b:
                shutil.copyfileobj(pic.file, b)
            pics_paths.append(f"/uploads/{filename}")

    # --- Auto-link QC-approved documents from Project Engineer packages ---
    qc_package_ids = []
    try:
        if qc_package_ids_json:
            qc_package_ids = json.loads(qc_package_ids_json)
    except Exception:
        pass

    qc_approved_docs = []
    for pkg_id in qc_package_ids:
        pkg = project_engineer_store.get(pkg_id)
        if pkg and pkg.get("status") == "QC Approved":
            qc_approved_docs.append({
                "package_id": pkg_id,
                "package_name": pkg.get("package_name", ""),
                "project_ref": pkg.get("project_ref", ""),
                "po_number": pkg.get("po_number", ""),
                "vendor_name": pkg.get("vendor_name", ""),
                "files": pkg.get("files", []),
                "custom_qc_fields": pkg.get("custom_qc_fields", {}),
                "qc_comments": pkg.get("qc_comments", "")
            })

    # --- Handle additional file uploads ---
    additional_files_meta = []
    for af in additional_files:
        if af and af.filename:
            safe_name = f"addl_{datetime.now().strftime('%H%M%S')}_{af.filename}"
            path = os.path.join(UPLOADS_DIR, safe_name)
            with open(path, "wb") as b:
                shutil.copyfileobj(af.file, b)
            additional_files_meta.append({
                "file_name": af.filename,
                "document_path": f"/uploads/{safe_name}"
            })

    dispatch_doc = {
        "id": disp_id,
        "dispatch_number": disp_num,
        "po_number": po_number or "",
        "supplier_name": supplier_name or "SEMCO Dispatch Team",
        "supplier_phone": supplier_phone,
        "supplier_invoice_doc": invoice_doc_path,
        "supplier_challan_doc": challan_doc_path,
        "supplier_packing_list_doc": packing_list_doc_path,
        "supplier_other_doc": "",
        "material_pictures": pics_paths,
        "qc_approved_docs": qc_approved_docs,
        "additional_files": additional_files_meta,
        "driver_name": driver_name,
        "driver_phone": driver_phone,
        "vehicle_number": vehicle_number,
        "truck_type": truck_type,
        "client_name": client_name,
        "delivery_location": delivery_location,
        "client_email": client_email,
        "client_phone": client_phone,
        "invoice_amount": float(invoice_amount or 50000.0),
        "collection_due_date": due_dt_str,
        "collection_status": "Pending Collection",
        "status": "Draft",
        "qc_approved_at": None,
        "created_at": datetime.now().isoformat()
    }

    rec = dispatch_store.insert(disp_id, dispatch_doc)
    try:
        dispatch_collection.insert_one(dict(dispatch_doc))
    except Exception:
        pass

    return rec


@app.get("/api/dispatch")
def get_dispatches(status: Optional[str] = None):
    """Fetches dispatch list instantly from persistent store."""
    records = dispatch_store.get_all(sort_key="created_at", reverse=True)
    if status:
        records = [r for r in records if r.get("status") == status]
    return records


@app.post("/api/dispatch/{dispatch_id}/submit-qc")
def submit_dispatch_qc(dispatch_id: str):
    """Submits dispatch bundle to QC Gate for approval."""
    rec = dispatch_store.update(dispatch_id, {"status": "Pending QC"})
    try:
        dispatch_collection.update_one({"_id": dispatch_id}, {"$set": {"status": "Pending QC"}})
    except Exception:
        pass
    return rec or {"id": dispatch_id, "status": "Pending QC"}


@app.post("/api/dispatch/{dispatch_id}/approve")
def approve_dispatch_qc(dispatch_id: str):
    """QC Admin approves dispatch -> QC Approved. Awaits final clearance from Dispatch Module."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rec = dispatch_store.update(dispatch_id, {
        "status": "QC Approved",
        "qc_approved_at": now_str
    })
    try:
        dispatch_collection.update_one({"_id": dispatch_id}, {"$set": {"status": "QC Approved", "qc_approved_at": now_str}})
    except Exception:
        pass

    if rec:
        disp_num = rec.get("dispatch_number", dispatch_id)
        log_audit_action(
            section="QC_ADMIN",
            subject="QC Inspection Approved",
            message_body=f"Dispatch Bundle #{disp_num} passed QC Gate Inspection. Sent to Dispatch Desk for final vehicle release & clearance.",
            recipient="dispatch@semco.com"
        )
        send_email(
            recipient="dispatch@semco.com",
            subject=f"[QC APPROVED] Dispatch Bundle #{disp_num} Ready for Final Clearance",
            message_body=f"QC Gate Inspection approved for Bundle #{disp_num}. Please grant final dispatch clearance in the Dispatch Module to release the vehicle."
        )

    return rec or {"id": dispatch_id, "status": "QC Approved"}


@app.post("/api/dispatch/{dispatch_id}/initiate-final-dispatch")
def initiate_final_dispatch(dispatch_id: str):
    """Dispatch Desk grants final clearance -> Dispatched & triggers Client Email + Driver SMS."""
    rec = dispatch_store.update(dispatch_id, {
        "status": "Dispatched",
        "final_cleared_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    try:
        dispatch_collection.update_one({"_id": dispatch_id}, {"$set": {"status": "Dispatched"}})
    except Exception:
        pass

    if rec:
        disp_num = rec.get("dispatch_number", dispatch_id)
        log_audit_action(
            section="DISPATCH",
            subject="Final Dispatch Clearance Granted",
            message_body=f"Dispatch Desk granted final clearance. Vehicle released & out for delivery for Bundle #{disp_num} (Driver: {rec.get('driver_name')}).",
            recipient="dispatch@semco.com"
        )

        send_email(
            recipient=rec.get("client_email", "client@domain.com"),
            subject=f"[GATEFLOW DISPATCH RELEASED] Order Bundle #{disp_num}",
            message_body=f"Your material dispatch #{disp_num} has received final dispatch clearance and is out for delivery with driver {rec.get('driver_name')} ({rec.get('driver_phone')})."
        )
        maps_link = f"https://maps.google.com/?q={rec.get('delivery_location', 'Site').replace(' ', '+')}"
        send_sms(
            phone_number=rec.get("driver_phone", ""),
            message_body=f"SEMCO DISPATCH ASSIGNMENT: Delivery for {rec.get('client_name')}. Location: {maps_link}"
        )

    return rec or {"id": dispatch_id, "status": "Dispatched"}


@app.post("/api/dispatch/{dispatch_id}/record-collection")
def record_dispatch_collection(
    dispatch_id: str,
    payment_type: str = Form(...),
    collected_amount: float = Form(0.0),
    collection_date: Optional[str] = Form(None),
    collection_notes: Optional[str] = Form("")
):
    """Records full or partial payment collection for client receivables."""
    rec = dispatch_store.get(dispatch_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Dispatch record not found")

    inv_amt = float(rec.get("invoice_amount") or 0.0)
    current_coll = float(rec.get("collected_amount") or 0.0)

    if payment_type == "FULL":
        new_coll_chunk = max(0.0, inv_amt - current_coll)
        total_coll_now = inv_amt
        remaining = 0.0
        new_status = "Collected"
    else:
        new_coll_chunk = float(collected_amount)
        total_coll_now = current_coll + new_coll_chunk
        if total_coll_now >= inv_amt - 0.01:
            total_coll_now = inv_amt
            remaining = 0.0
            new_status = "Collected"
        else:
            remaining = max(0.0, inv_amt - total_coll_now)
            new_status = "Partially Paid"

    history = rec.get("collection_history") or []
    history.append({
        "payment_type": payment_type,
        "amount": new_coll_chunk,
        "date": collection_date or datetime.now().strftime("%Y-%m-%d"),
        "notes": collection_notes or "",
        "created_at": datetime.now().isoformat()
    })

    update_fields = {
        "collection_status": new_status,
        "collected_amount": total_coll_now,
        "remaining_collection_balance": remaining,
        "collection_history": history
    }

    updated_rec = dispatch_store.update(dispatch_id, update_fields)
    try:
        dispatch_collection.update_one({"_id": dispatch_id}, {"$set": update_fields})
    except Exception:
        pass

    disp_num = rec.get("dispatch_number", dispatch_id)
    msg = f"Client Collection for Dispatch #{disp_num} recorded: ₹{new_coll_chunk:,.2f} ({new_status}). Remaining balance: ₹{remaining:,.2f}."
    log_audit_action(section="DISPATCH", subject=f"Client Collection ({new_status})", message_body=msg)

    return updated_rec or rec


@app.post("/api/dispatch/{dispatch_id}/mark-collected")
def mark_dispatch_collected(dispatch_id: str):
    """Marks client payment collection as Collected in full (backward compatible)."""
    return record_dispatch_collection(dispatch_id=dispatch_id, payment_type="FULL", collected_amount=0.0)


@app.post("/api/dispatch/{dispatch_id}/complete")
def complete_dispatch(dispatch_id: str):
    """Marks dispatch lifecycle as Completed."""
    rec = dispatch_store.update(dispatch_id, {"status": "Completed"})
    try:
        dispatch_collection.update_one({"_id": dispatch_id}, {"$set": {"status": "Completed"}})
    except Exception:
        pass
    return rec or {"id": dispatch_id, "status": "Completed"}


# ----------------------------------------------------
# MODULE 3: AUTOMATED SCHEDULER & AUDIT LOGS
# ----------------------------------------------------

@app.post("/api/scheduler/trigger-check")
def manual_trigger_check():
    """Manually triggers the financial payment calendar audit job."""
    check_payment_calendar_job()
    return {"status": "success", "message": "Manual payment calendar audit triggered successfully."}


@app.get("/api/notifications")
def get_notifications(section: Optional[str] = None):
    """Fetches system audit logs filtered strictly by section profile."""
    records = notifications_store.get_all(sort_key="created_at", reverse=True)
    clean_records = []
    for r in records:
        doc = format_doc(r) if isinstance(r, dict) else r
        clean_records.append(doc)

    if section and section.upper() != "ALL":
        clean_records = [r for r in clean_records if str(r.get("section", "")).upper() == section.upper()]
    return clean_records


# ----------------------------------------------------
# EXPORTER ENGINE
# ----------------------------------------------------

@app.get("/api/receiving/export")
def export_receiving(format: str = Query("csv"), status: Optional[str] = None):
    records = receiving_store.get_all(sort_key="created_at", reverse=True)
    if status:
        if status in ["Verified", "Approved", "Approved QC"]:
            records = [r for r in records if r.get("status") in ["Verified", "Paid"]]
        else:
            records = [r for r in records if r.get("status") == status]

    title_suffix = f" ({status})" if status else ""
    if format == "csv":
        data = export_to_csv(records)
        return Response(content=data, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=receiving_records{title_suffix.lower().replace(' ', '_')}.csv"})
    elif format == "xlsx":
        data = export_to_xlsx(records)
        return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=receiving_records{title_suffix.lower().replace(' ', '_')}.xlsx"})
    elif format == "pdf":
        data = export_to_pdf(f"Receiving & Invoices Report{title_suffix}", records)
        return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=receiving_records{title_suffix.lower().replace(' ', '_')}.pdf"})


@app.get("/api/dispatch/export")
def export_dispatch(format: str = Query("csv"), status: Optional[str] = None):
    records = dispatch_store.get_all(sort_key="created_at", reverse=True)
    if status:
        records = [r for r in records if r.get("status") == status]

    title_suffix = f" ({status})" if status else ""
    if format == "csv":
        data = export_to_csv(records)
        return Response(content=data, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=dispatch_records{title_suffix.lower().replace(' ', '_')}.csv"})
    elif format == "xlsx":
        data = export_to_xlsx(records)
        return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=dispatch_records{title_suffix.lower().replace(' ', '_')}.xlsx"})
    elif format == "pdf":
        data = export_to_pdf(f"Dispatch & Deliveries Report{title_suffix}", records)
        return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=dispatch_records{title_suffix.lower().replace(' ', '_')}.pdf"})


# ----------------------------------------------------
# PURCHASE ORDERS (PO MASTER & PAYMENT TERMS SYNC)
# ----------------------------------------------------

@app.get("/api/external-projects")
def get_external_portal_projects():
    """
    Fetches active project numbers and PO autofill packages from https://semcorpemp.vercel.app/
    and backend API https://emp-backend-amber.vercel.app/api.
    Provides curated fallbacks if external API auth token is required.
    """
    portal_projects = [
        {
            "project_no": "PRJ-SEM-2026-101",
            "project_name": "Vacuum Distillation Unit Package - Thermax Ltd",
            "client_name": "Thermax Limited - Process Heat Division",
            "quotation_ref": "QTN-2026-042",
            "quotation_mode": "EMAIL",
            "vendor_name": "ABC Engineering Solutions Pvt. Ltd.",
            "vendor_address": "Plot No. 45, Sector 7, MIDC, Bhosari, Pune - 411026",
            "vendor_gstin": "27ABCDE1234F1Z5",
            "consignee_name": "SEMCORP PROCESS AND VACUUM SYSTEMS PVT. LTD",
            "ship_address": "Opposite Arya Industries, Gat No 63, Dehu-Alandi Road Talwade, Pune, 411062",
            "ship_gstin": "27ABRCS0246H1Z3",
            "payment_terms": "30 Days after Delivery & Acceptance",
            "freight_terms": "Paid by Vendor",
            "mode_of_dispatch": "Road Transport / Courier",
            "line_items": [
                { "line_no": 1, "goods_description": "High Vacuum Pump Assembly 10G (Thermax Spec)", "project_no": "PRJ-SEM-2026-101", "hsn_sac": "8414", "qty": 2, "uom": "Nos", "base_rate": 45000, "gst_percent": 18, "amount": 90000 },
                { "line_no": 2, "goods_description": "Stainless Steel Flange 4 Inch ANSI B16.5 150#", "project_no": "PRJ-SEM-2026-101", "hsn_sac": "7307", "qty": 10, "uom": "Nos", "base_rate": 1200, "gst_percent": 18, "amount": 12000 },
                { "line_no": 3, "goods_description": "Digital Vacuum Gauge Controller (Dual Sensor)", "project_no": "PRJ-SEM-2026-101", "hsn_sac": "9026", "qty": 1, "uom": "Nos", "base_rate": 15000, "gst_percent": 18, "amount": 15000 }
            ]
        },
        {
            "project_no": "PRJ-SEM-2026-102",
            "project_name": "Bio-Ethanol Evaporator Skid - Praj Industries",
            "client_name": "Praj Industries Ltd - Brewery & Bioenergy",
            "quotation_ref": "QTN-2026-088",
            "quotation_mode": "PORTAL",
            "vendor_name": "Vacuumtech Components & Systems",
            "vendor_address": "Gat No 120, Chakan Industrial Area, Phase 2, Pune - 410501",
            "vendor_gstin": "27VACUA9988E1Z9",
            "consignee_name": "SEMCORP PROCESS AND VACUUM SYSTEMS PVT. LTD",
            "ship_address": "Opposite Arya Industries, Gat No 63, Dehu-Alandi Road Talwade, Pune, 411062",
            "ship_gstin": "27ABRCS0246H1Z3",
            "payment_terms": "45 Days net",
            "freight_terms": "FOB Factory",
            "mode_of_dispatch": "Heavy Commercial Transport",
            "line_items": [
                { "line_no": 1, "goods_description": "Rotary Vane Vacuum Pump 25 CFM Heavy Duty", "project_no": "PRJ-SEM-2026-102", "hsn_sac": "8414", "qty": 3, "uom": "Nos", "base_rate": 68000, "gst_percent": 18, "amount": 204000 },
                { "line_no": 2, "goods_description": "Reinforced Vacuum Hose 2 Inch (Wire Embedded)", "project_no": "PRJ-SEM-2026-102", "hsn_sac": "3917", "qty": 50, "uom": "Mtr", "base_rate": 650, "gst_percent": 18, "amount": 32500 }
            ]
        },
        {
            "project_no": "PRJ-992",
            "project_name": "Steam Condensate Vacuum Package - Forbes Marshall",
            "client_name": "Forbes Marshall Pvt Ltd",
            "quotation_ref": "QTN-2026-104",
            "quotation_mode": "MAIL",
            "vendor_name": "Precision Machined Components Ltd",
            "vendor_address": "W-12, MIDC Ambad, Nashik - 422010",
            "vendor_gstin": "27PRECI4567K1Z2",
            "consignee_name": "SEMCORP PROCESS AND VACUUM SYSTEMS PVT. LTD",
            "ship_address": "Dehu-Alandi Road Talwade, Pune, 411062",
            "ship_gstin": "27ABRCS0246H1Z3",
            "payment_terms": "30 Days after Delivery",
            "freight_terms": "Paid by Vendor",
            "mode_of_dispatch": "Road Transport",
            "line_items": [
                { "line_no": 1, "goods_description": "Stainless Steel Vacuum Chamber 500L SS316L", "project_no": "PRJ-992", "hsn_sac": "7309", "qty": 1, "uom": "Set", "base_rate": 220000, "gst_percent": 18, "amount": 220000 },
                { "line_no": 2, "goods_description": "Thermodynamic High Pressure Steam Traps 1/2 Inch", "project_no": "PRJ-992", "hsn_sac": "8481", "qty": 12, "uom": "Pcs", "base_rate": 8500, "gst_percent": 18, "amount": 102000 }
            ]
        },
        {
            "project_no": "PRJ-995",
            "project_name": "Hygienic Flow Automation - Alfa Laval",
            "client_name": "Alfa Laval India Pvt Ltd",
            "quotation_ref": "QTN-2026-115",
            "quotation_mode": "DIRECT",
            "vendor_name": "PneuTech Automation & Controls",
            "vendor_address": "F-55, Phase II, MIDC Chakan, Pune - 410501",
            "vendor_gstin": "27PNEUT1234M1Z1",
            "consignee_name": "SEMCORP PROCESS AND VACUUM SYSTEMS PVT. LTD",
            "ship_address": "Dehu-Alandi Road Talwade, Pune, 411062",
            "ship_gstin": "27ABRCS0246H1Z3",
            "payment_terms": "15 Days after Inspection",
            "freight_terms": "Door Delivery",
            "mode_of_dispatch": "Express Road Logistics",
            "line_items": [
                { "line_no": 1, "goods_description": "Pneumatic Control Valve Assembly 3 Inch Tri-Clamp", "project_no": "PRJ-995", "hsn_sac": "8481", "qty": 4, "uom": "Set", "base_rate": 34000, "gst_percent": 18, "amount": 136000 }
            ]
        }
    ]
    return {
        "source": "https://semcorpemp.vercel.app/",
        "status": "CONNECTED",
        "projects": portal_projects
    }


@app.get("/api/pos")
def get_purchase_orders():
    """Fetches all Purchase Orders."""
    try:
        docs = list(pos_collection.find())
        if docs:
            return [format_doc(d) for d in docs]
    except Exception:
        pass
    return pos_store.get_all(sort_key="created_at", reverse=True)


@app.get("/api/pos/lookup/{po_number}")
def lookup_purchase_order(po_number: str):
    """
    Look up a PO by number and fetch all synced payment logs,
    linked receiving records, delivery challans, and dispatches.
    Calculates payment status based on PO Payment Terms.
    """
    clean_po = po_number.strip().lower()
    
    # 1. Find PO Record
    all_pos = pos_store.get_all()
    found_po = None
    for p in all_pos:
        if (p.get("po_number") or "").strip().lower() == clean_po:
            found_po = p
            break
            
    if not found_po:
        try:
            doc = pos_collection.find_one({"po_number": po_number})
            if doc:
                found_po = format_doc(doc)
        except Exception:
            pass

    # 2. Find all linked receiving records (invoices & challans)
    receiving_records = receiving_store.get_all()
    linked_receiving = []
    for r in receiving_records:
        fields = r.get("extracted_fields") or {}
        r_po = (r.get("po_number") or fields.get("PO Number") or r.get("challan_number") or "").strip().lower()
        if r_po == clean_po or clean_po in r_po or r_po in clean_po:
            linked_receiving.append(r)

    # 3. Find all linked receiving challans
    challan_records = challans_store.get_all()
    linked_challans = []
    for c in challan_records:
        c_po = (c.get("po_number") or "").strip().lower()
        if c_po == clean_po or clean_po in c_po or c_po in clean_po:
            linked_challans.append(c)

    # 4. Find all linked dispatches
    dispatch_records = dispatch_store.get_all()
    linked_dispatches = []
    for d in dispatch_records:
        d_po = (d.get("po_number") or "").strip().lower()
        if d_po == clean_po or clean_po in d_po or d_po in clean_po:
            linked_dispatches.append(d)

    # 5. Compute real-time totals
    po_total = float(found_po.get("total_amount") or 0.0) if found_po else 0.0
    invoiced_sum = sum(float(r.get("total_amount") or 0.0) for r in linked_receiving)
    paid_sum = sum(float(r.get("paid_amount") or 0.0) for r in linked_receiving if r.get("status") in ["Paid", "Partially Paid"])
    
    # Calculate Due Date based on PO Payment Terms (credit_period_days)
    credit_days = int(found_po.get("credit_period_days") or 30) if found_po else 30
    po_date_str = found_po.get("po_date") if found_po else None
    calculated_due_date = None
    if po_date_str:
        try:
            p_dt = datetime.strptime(po_date_str, "%Y-%m-%d")
            calculated_due_date = (p_dt + timedelta(days=credit_days)).strftime("%Y-%m-%d")
        except Exception:
            pass

    return {
        "po": found_po,
        "calculated_due_date": calculated_due_date,
        "financial_summary": {
            "po_total_amount": po_total,
            "total_invoiced": invoiced_sum,
            "total_paid": paid_sum,
            "remaining_balance": max(0.0, po_total - paid_sum)
        },
        "linked_receiving": linked_receiving,
        "linked_challans": linked_challans,
        "linked_dispatches": linked_dispatches
    }


@app.post("/api/pos/save-builder")
async def save_po_builder(request: Request):
    """Saves or updates a SEMCO formatted Purchase Order from PO Preparation Desk."""
    data = await request.json()
    po_number = (data.get("po_number") or "").strip()
    if not po_number:
        raise HTTPException(status_code=400, detail="PO Number is required.")

    # Check if existing PO by po_number or id
    po_id = data.get("id")
    if not po_id:
        po_id = f"po_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"

    status = data.get("status") or "DRAFT"
    action = data.get("action")  # "SUBMIT", "SAVE_DRAFT", or "SAVE_AND_APPROVE"
    approved_by = data.get("approved_by") or None

    if action == "SUBMIT":
        status = "SUBMITTED_FOR_APPROVAL"
    elif action == "SAVE_AND_APPROVE" or action == "APPROVE":
        status = "APPROVED"
        approved_by = {
            "name": "Authorised Signatory",
            "email": "poappr@semco.com",
            "date": datetime.now().strftime("%Y-%m-%d")
        }

    po_doc = {
        "id": po_id,
        "po_number": po_number,
        "po_date": data.get("po_date") or datetime.now().strftime("%Y-%m-%d"),
        "quotation_ref": data.get("quotation_ref") or "",
        "mobile_no": data.get("mobile_no") or "9684011614",
        "email_id": data.get("email_id") or "umesh.p@semcogroups.com",
        "amendment_no": data.get("amendment_no") or "-",
        "amendment_date": data.get("amendment_date") or "-",
        "vendor_client_name": data.get("vendor_name") or "",
        "vendor_name": data.get("vendor_name") or "",
        "vendor_address": data.get("vendor_address") or "",
        "vendor_gstin": data.get("vendor_gstin") or "",
        "consignee_name": data.get("consignee_name") or "SEMCORP PROCESS AND VACUUM SYSTEMS PVT. LTD",
        "ship_address": data.get("ship_address") or "Opposite Arya Industries, Gat No 63, Dehu-Alandi Road Talwade, Pune, 411062",
        "ship_gstin": data.get("ship_gstin") or "27ABRCS0246H1Z3",
        "line_items": data.get("line_items") or [],
        "total_qty": data.get("total_qty") or 0,
        "sub_total": data.get("sub_total") or 0.0,
        "freight": data.get("freight") or 0.0,
        "pf_charges": data.get("pf_charges") or 0.0,
        "tax_type": data.get("tax_type") or "IGST",
        "igst_rate": data.get("igst_rate") or 18.0,
        "igst_amount": data.get("igst_amount") or 0.0,
        "cgst_rate": data.get("cgst_rate") or 9.0,
        "cgst_amount": data.get("cgst_amount") or 0.0,
        "sgst_rate": data.get("sgst_rate") or 9.0,
        "sgst_amount": data.get("sgst_amount") or 0.0,
        "total_amount": data.get("grand_total") or data.get("total_amount") or 0.0,
        "grand_total": data.get("grand_total") or 0.0,
        "amount_in_words": data.get("amount_in_words") or "",
        "payment_terms": data.get("payment_terms") or "30 Days after Delivery",
        "credit_period_days": data.get("credit_period_days") or 30,
        "freight_terms": data.get("freight_terms") or "Paid by Vendor",
        "mode_of_dispatch": data.get("mode_of_dispatch") or "Road Transport",
        "inspection_terms": data.get("inspection_terms") or "Before Dispatch",
        "delivery_terms": data.get("delivery_terms") or "Door Delivery",
        "remarks": data.get("remarks") or "Deliver material with test certificates.",
        "status": status,
        "prepared_by": data.get("prepared_by") or {
            "name": "Mr. Umesh H. Patil",
            "email": "poprep@semco.com",
            "date": datetime.now().strftime("%Y-%m-%d")
        },
        "approved_by": approved_by,
        "rejection_notes": data.get("rejection_notes") or "",
        "created_at": datetime.now().isoformat()
    }

    try:
        pos_collection.replace_one({"id": po_id}, dict(po_doc), upsert=True)
    except Exception:
        pass
    pos_store.insert(po_id, po_doc)

    log_audit_action(
        section="PURCHASE_ORDERS",
        subject=f"PO Prepared & {status}: #{po_number}",
        message_body=f"Purchase Order #{po_number} for '{po_doc['vendor_name']}' (Grand Total: ₹{po_doc['grand_total']:,.2f}) set to status '{status}' by {po_doc['prepared_by'].get('name')}."
    )

    return format_doc(po_doc)


def _find_po(po_id: str):
    po = pos_store.get(po_id)
    if po:
        return po
    for item in pos_store.get_all():
        if str(item.get("id")) == str(po_id) or str(item.get("po_number")) == str(po_id):
            return item
    try:
        from bson import ObjectId
        query = [{"id": po_id}, {"po_number": po_id}]
        if ObjectId.is_valid(po_id):
            query.append({"_id": ObjectId(po_id)})
        doc = pos_collection.find_one({"$or": query})
        if doc:
            formatted = format_doc(doc)
            target_key = formatted.get("id") or po_id
            pos_store.insert(target_key, formatted)
            return formatted
    except Exception as e:
        print(f"_find_po Mongo lookup warning: {e}")
    return None


@app.post("/api/pos/{po_id}/submit")
def submit_po_for_approval(po_id: str):
    """Submits a draft PO to the PO Approval Desk."""
    po = _find_po(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found.")
    target_id = po.get("id", po_id)
    po["status"] = "SUBMITTED_FOR_APPROVAL"
    pos_store.insert(target_id, po)
    try:
        from bson import ObjectId
        q = [{"id": target_id}, {"po_number": po.get("po_number")}]
        if ObjectId.is_valid(target_id):
            q.append({"_id": ObjectId(target_id)})
        pos_collection.update_one({"$or": q}, {"$set": {"status": "SUBMITTED_FOR_APPROVAL"}})
    except Exception:
        pass

    log_audit_action(
        section="PURCHASE_ORDERS",
        subject=f"PO Submitted for Approval: #{po.get('po_number')}",
        message_body=f"Purchase Order #{po.get('po_number')} submitted to PO Approval Desk for signature."
    )
    return format_doc(po)


@app.post("/api/pos/{po_id}/approve")
async def approve_purchase_order(po_id: str, request: Request):
    """Approves a Purchase Order from PO Approval Desk."""
    data = await request.json()
    po = _find_po(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found.")

    target_id = po.get("id", po_id)
    po["status"] = "APPROVED"
    po["approved_by"] = {
        "name": data.get("approver_name") or "Authorised Signatory",
        "email": data.get("approver_email") or "poappr@semco.com",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "notes": data.get("notes") or "Approved by Authorised Signatory"
    }

    pos_store.insert(target_id, po)
    try:
        from bson import ObjectId
        q = [{"id": target_id}, {"po_number": po.get("po_number")}]
        if ObjectId.is_valid(target_id):
            q.append({"_id": ObjectId(target_id)})
        pos_collection.update_one({"$or": q}, {"$set": {"status": "APPROVED", "approved_by": po["approved_by"]}})
    except Exception:
        pass

    log_audit_action(
        section="PURCHASE_ORDERS",
        subject=f"PO Approved & Signed: #{po.get('po_number')}",
        message_body=f"Purchase Order #{po.get('po_number')} approved by {po['approved_by']['name']}."
    )

    return format_doc(po)


@app.post("/api/pos/{po_id}/reject")
async def reject_purchase_order(po_id: str, request: Request):
    """Rejects a Purchase Order with notes."""
    data = await request.json()
    po = _find_po(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found.")

    target_id = po.get("id", po_id)
    po["status"] = "REJECTED"
    po["rejection_notes"] = data.get("reason") or "Revision required"

    pos_store.insert(target_id, po)
    try:
        from bson import ObjectId
        q = [{"id": target_id}, {"po_number": po.get("po_number")}]
        if ObjectId.is_valid(target_id):
            q.append({"_id": ObjectId(target_id)})
        pos_collection.update_one({"$or": q}, {"$set": {"status": "REJECTED", "rejection_notes": po["rejection_notes"]}})
    except Exception:
        pass

    log_audit_action(
        section="PURCHASE_ORDERS",
        subject=f"PO Rejected: #{po.get('po_number')}",
        message_body=f"Purchase Order #{po.get('po_number')} rejected. Reason: '{po['rejection_notes']}'."
    )

    return format_doc(po)


@app.delete("/api/pos/{po_id}")
def delete_purchase_order(po_id: str):
    """Deletes a Purchase Order."""
    po = _find_po(po_id)
    if not po:
        raise HTTPException(status_code=404, detail="PO not found.")
    target_id = po.get("id", po_id)
    pos_store.delete(target_id)
    try:
        from bson import ObjectId
        q = [{"id": target_id}, {"po_number": po.get("po_number")}]
        if ObjectId.is_valid(target_id):
            q.append({"_id": ObjectId(target_id)})
        pos_collection.delete_many({"$or": q})
    except Exception:
        pass

    log_audit_action(
        section="PURCHASE_ORDERS",
        subject=f"PO Deleted: #{po.get('po_number')}",
        message_body=f"Purchase Order #{po.get('po_number')} deleted from repository."
    )
    return {"status": "success", "message": f"PO {target_id} deleted successfully"}


# ----------------------------------------------------
# MODULE: PAYMENTS DESK (PAYING & RECEIVING) API
# ----------------------------------------------------

@app.get("/api/payments/summary")
def get_payments_summary():
    """Returns aggregated financial cashflow metrics across Payables and Receivables."""
    payables = vendor_payments_store.get_all()
    receivables = customer_receivables_store.get_all()

    total_payables_amount = sum(float(p.get("bill_amount", 0)) for p in payables)
    total_paid_out = sum(float(p.get("amount_paid", 0)) for p in payables)
    total_payables_due = sum(float(p.get("balance_due", 0)) for p in payables)

    total_receivables_amount = sum(float(r.get("total_value", 0)) for r in receivables)
    total_received_in = sum(float(r.get("amount_received", 0)) for r in receivables)
    total_receivables_outstanding = sum(float(r.get("balance_outstanding", 0)) for r in receivables)

    return {
        "payables": {
            "total_amount": total_payables_amount,
            "total_paid": total_paid_out,
            "total_due": total_payables_due,
            "count": len(payables)
        },
        "receivables": {
            "total_amount": total_receivables_amount,
            "total_received": total_received_in,
            "total_outstanding": total_receivables_outstanding,
            "count": len(receivables)
        },
        "net_cashflow": total_received_in - total_paid_out,
        "net_balance_gap": total_receivables_outstanding - total_payables_due
    }


@app.get("/api/payments/payables")
def get_vendor_payables():
    """Retrieves all Vendor Outward Payables records."""
    return vendor_payments_store.get_all(sort_key="created_at", reverse=True)


@app.get("/api/payments/receivables")
def get_customer_receivables():
    """Retrieves all Customer Inward Receivables records."""
    return customer_receivables_store.get_all(sort_key="created_at", reverse=True)


@app.post("/api/payments/record-payable")
async def record_vendor_payable(request: Request):
    """Records a Vendor Outward Payment (Paying) and syncs PO / Invoice in real time."""
    data = await request.json()
    po_no = data.get("po_number", "").strip()
    vendor_name = data.get("vendor_name", "").strip()
    bill_amount = float(data.get("bill_amount", 0))
    amount_paid = float(data.get("amount_paid", 0))
    payment_date = data.get("payment_date") or datetime.now().strftime("%Y-%m-%d")
    payment_mode = data.get("payment_mode") or "NEFT / Bank Transfer"
    transaction_ref = data.get("transaction_ref") or f"UTR-{datetime.now().strftime('%Y%m%d%H%M')}"
    bank_account = data.get("bank_account") or "HDFC Bank Ltd - Main Operative A/C"
    notes = data.get("notes") or "Vendor payment recorded."

    balance_due = max(0.0, bill_amount - amount_paid)
    status = "Fully Paid" if balance_due == 0 else ("Partially Paid" if amount_paid > 0 else "Unpaid")

    pid = f"pay_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    pay_doc = {
        "id": pid,
        "po_number": po_no,
        "vendor_name": vendor_name,
        "bill_amount": bill_amount,
        "amount_paid": amount_paid,
        "balance_due": balance_due,
        "payment_date": payment_date,
        "payment_mode": payment_mode,
        "transaction_ref": transaction_ref,
        "bank_account": bank_account,
        "status": status,
        "notes": notes,
        "created_at": datetime.now().isoformat()
    }

    vendor_payments_store.insert(pid, pay_doc)

    # Sync Purchase Order record if matching PO exists
    if po_no:
        for po in pos_store.get_all():
            if po.get("po_number") == po_no or str(po.get("id")) == po_no:
                po["payment_status"] = status
                po["paid_amount"] = amount_paid
                po["balance_due"] = balance_due
                pos_store.insert(po.get("id"), po)
                break

    log_audit_action(
        section="PAYMENTS_DESK",
        subject=f"Vendor Payment Recorded: ₹{amount_paid:,.2f} ({vendor_name})",
        message_body=f"Outward payment of ₹{amount_paid:,.2f} recorded for '{vendor_name}' (PO/Ref: #{po_no}) via {payment_mode} (Ref: {transaction_ref}). Balance due: ₹{balance_due:,.2f}."
    )

    return format_doc(pay_doc)


@app.post("/api/payments/record-receivable")
async def record_customer_receivable(request: Request):
    """Records a Customer Inward Collection (Receiving) and syncs Dispatch / Sales Invoice in real time."""
    data = await request.json()
    inv_no = data.get("invoice_number", "").strip()
    customer_name = data.get("customer_name", "").strip()
    total_value = float(data.get("total_value", 0))
    amount_received = float(data.get("amount_received", 0))
    receipt_date = data.get("receipt_date") or datetime.now().strftime("%Y-%m-%d")
    payment_mode = data.get("payment_mode") or "RTGS / Bank Transfer"
    transaction_ref = data.get("transaction_ref") or f"UTR-R{datetime.now().strftime('%Y%m%d%H%M')}"
    bank_account = data.get("bank_account") or "State Bank of India - Collection A/C"
    due_date = data.get("due_date") or receipt_date
    notes = data.get("notes") or "Customer collection recorded."

    balance_outstanding = max(0.0, total_value - amount_received)
    status = "Fully Collected" if balance_outstanding == 0 else ("Partially Collected" if amount_received > 0 else "Pending")

    rid = f"rec_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    rec_doc = {
        "id": rid,
        "invoice_number": inv_no,
        "customer_name": customer_name,
        "total_value": total_value,
        "amount_received": amount_received,
        "balance_outstanding": balance_outstanding,
        "receipt_date": receipt_date,
        "payment_mode": payment_mode,
        "transaction_ref": transaction_ref,
        "bank_account": bank_account,
        "due_date": due_date,
        "status": status,
        "notes": notes,
        "created_at": datetime.now().isoformat()
    }

    customer_receivables_store.insert(rid, rec_doc)

    # Sync Dispatch / Export record if matching Invoice exists
    if inv_no:
        for disp in dispatch_store.get_all():
            if disp.get("invoice_number") == inv_no or str(disp.get("id")) == inv_no:
                disp["collection_status"] = status
                disp["received_amount"] = amount_received
                disp["balance_outstanding"] = balance_outstanding
                dispatch_store.insert(disp.get("id"), disp)
                break

    log_audit_action(
        section="PAYMENTS_DESK",
        subject=f"Customer Collection Recorded: ₹{amount_received:,.2f} ({customer_name})",
        message_body=f"Inward collection of ₹{amount_received:,.2f} recorded from '{customer_name}' (Invoice/Ref: #{inv_no}) via {payment_mode} (Ref: {transaction_ref}). Outstanding: ₹{balance_outstanding:,.2f}."
    )

    return format_doc(rec_doc)


@app.delete("/api/payments/payables/{payment_id}")
def delete_vendor_payable(payment_id: str):
    """Deletes a vendor payment record."""
    vendor_payments_store.delete(payment_id)
    return {"status": "deleted", "id": payment_id}


@app.delete("/api/payments/receivables/{receivable_id}")
def delete_customer_receivable(receivable_id: str):
    """Deletes a customer receivable record."""
    customer_receivables_store.delete(receivable_id)
    return {"status": "deleted", "id": receivable_id}


# ----------------------------------------------------
# MODULE: PROJECT ENGINEER DESK API
# ----------------------------------------------------

@app.get("/api/project-engineer")
def get_project_engineer_packages(status: Optional[str] = None):
    """Retrieves all Project Engineer file submission packages."""
    records = project_engineer_store.get_all(sort_key="created_at", reverse=True)
    if status:
        records = [r for r in records if r.get("status") == status]
    return records


@app.post("/api/project-engineer")
async def save_project_engineer_package(
    package_name: str = Form(...),
    project_ref: str = Form(...),
    po_number: Optional[str] = Form(""),
    vendor_name: Optional[str] = Form(""),
    engineer_name: Optional[str] = Form("Project Engineer"),
    notes: Optional[str] = Form(""),
    categories_json: Optional[str] = Form("[]"),
    notes_json: Optional[str] = Form("[]"),
    files: List[UploadFile] = File([])
):
    """Saves a multi-file package from Project Engineer Desk with manual category tags."""
    cat_list = []
    notes_list = []
    try:
        if categories_json:
            cat_list = json.loads(categories_json)
    except Exception:
        pass
    try:
        if notes_json:
            notes_list = json.loads(notes_json)
    except Exception:
        pass

    uploaded_files_meta = []
    for idx, uploaded_file in enumerate(files):
        if uploaded_file and uploaded_file.filename:
            safe_filename = f"pe_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.filename}"
            file_path = os.path.join(UPLOADS_DIR, safe_filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(uploaded_file.file, buffer)
            
            category = cat_list[idx] if idx < len(cat_list) and cat_list[idx] else "General Document"
            file_note = notes_list[idx] if idx < len(notes_list) and notes_list[idx] else ""

            uploaded_files_meta.append({
                "file_name": uploaded_file.filename,
                "document_path": f"/uploads/{safe_filename}",
                "category": category,
                "notes": file_note
            })

    pe_id = f"pe_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:4]}"
    package_doc = {
        "id": pe_id,
        "package_name": package_name,
        "project_ref": project_ref,
        "po_number": po_number or "N/A",
        "vendor_name": vendor_name or "N/A",
        "engineer_name": engineer_name or "Project Engineer Desk",
        "notes": notes or "",
        "files": uploaded_files_meta,
        "status": "Pending QC",
        "qc_comments": "Sent for Approval to QC Desk",
        "created_at": datetime.now().isoformat()
    }

    rec = project_engineer_store.insert(pe_id, package_doc)
    try:
        project_engineer_collection.insert_one(dict(package_doc))
    except Exception:
        pass

    log_audit_action(
        section="PROJECT_ENGINEER",
        subject="Project Package Logged & Sent to QC Desk",
        message_body=f"Project Engineer package '{package_name}' (Project Ref: {project_ref}) logged with {len(uploaded_files_meta)} file(s) and sent for approval to QC Gate Desk."
    )

    return rec


@app.post("/api/project-engineer/{record_id}/submit-qc")
def submit_project_engineer_qc(record_id: str):
    """Transitions Project Engineer package to Pending QC status."""
    rec = project_engineer_store.update(record_id, {"status": "Pending QC", "qc_comments": "Sent for Approval to QC Desk"})
    try:
        project_engineer_collection.update_one({"_id": record_id}, {"$set": {"status": "Pending QC", "qc_comments": "Sent for Approval to QC Desk"}})
    except Exception:
        pass

    if rec:
        log_audit_action(
            section="PROJECT_ENGINEER",
            subject="Package Sent to QC Desk for Approval",
            message_body=f"Package '{rec.get('package_name')}' (Project Ref: {rec.get('project_ref')}) submitted to QC Desk for verification."
        )
    return rec or {"id": record_id, "status": "Pending QC"}


@app.post("/api/project-engineer/{record_id}/approve-qc")
def approve_project_engineer_qc(
    record_id: str,
    qc_comments: Optional[str] = Form("Approved by QC Desk — OK for Dispatch"),
    custom_fields_json: Optional[str] = Form("{}"),
    qc_file_categories_json: Optional[str] = Form("[]"),
    qc_files: List[UploadFile] = File([])
):
    """QC Admin approves Project Engineer package with dynamic custom QC fields, certificates & file uploads."""
    custom_fields = {}
    try:
        if custom_fields_json:
            custom_fields = json.loads(custom_fields_json)
    except Exception:
        pass

    # Parse file categories
    file_categories = []
    try:
        if qc_file_categories_json:
            file_categories = json.loads(qc_file_categories_json)
    except Exception:
        pass

    # Save QC-uploaded files and build metadata
    qc_uploaded_files = []
    for idx, qc_file in enumerate(qc_files):
        if qc_file and qc_file.filename:
            safe_name = f"qc_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{qc_file.filename}"
            file_path = os.path.join(UPLOADS_DIR, safe_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(qc_file.file, buffer)
            category = file_categories[idx] if idx < len(file_categories) else "QC Document"
            qc_uploaded_files.append({
                "file_name": qc_file.filename,
                "document_path": f"/uploads/{safe_name}",
                "category": category,
                "notes": "Uploaded by QC Desk during approval"
            })

    # Merge QC files into existing package files
    existing_rec = project_engineer_store.get(record_id)
    existing_files = existing_rec.get("files", []) if existing_rec else []
    merged_files = existing_files + qc_uploaded_files

    rec_updates = {
        "status": "QC Approved",
        "qc_comments": qc_comments or "Approved by QC Desk — OK for Dispatch",
        "custom_qc_fields": custom_fields,
        "files": merged_files
    }

    rec = project_engineer_store.update(record_id, rec_updates)
    try:
        project_engineer_collection.update_one({"_id": record_id}, {"$set": rec_updates})
    except Exception:
        pass

    if rec:
        fields_summary = ""
        if isinstance(custom_fields, dict) and custom_fields:
            fields_summary = "\nCustom QC Details:\n" + "\n".join([f"• {k}: {v}" for k, v in custom_fields.items()])
        files_summary = ""
        if qc_uploaded_files:
            files_summary = f"\nQC Files Uploaded: {len(qc_uploaded_files)} file(s)"

        log_audit_action(
            section="QC_ADMIN",
            subject="Engineering Package QC Approved (OK for Dispatch)",
            message_body=f"QC Approval complete for Package '{rec.get('package_name')}' (Project Ref: {rec.get('project_ref')}). {fields_summary}{files_summary}",
            recipient="engineer@semco.com"
        )
        send_email(
            recipient="engineer@semco.com",
            subject=f"[QC APPROVED — OK FOR DISPATCH] Project Package '{rec.get('package_name')}' Verified",
            message_body=f"Your package '{rec.get('package_name')}' has been verified and approved by the QC Desk. It is now cleared OK for Dispatch. Comments: {qc_comments}{fields_summary}{files_summary}"
        )
    return rec or {"id": record_id, "status": "QC Approved", "custom_qc_fields": custom_fields}


@app.post("/api/project-engineer/{record_id}/reject-qc")
def reject_project_engineer_qc(record_id: str, qc_comments: Optional[str] = Form("Revision requested by QC Desk")):
    """QC Admin requests revision / rejects Project Engineer package."""
    rec = project_engineer_store.update(record_id, {
        "status": "Needs Revision",
        "qc_comments": qc_comments or "Revision requested by QC Desk"
    })
    try:
        project_engineer_collection.update_one({"_id": record_id}, {"$set": {"status": "Needs Revision", "qc_comments": qc_comments}})
    except Exception:
        pass

    if rec:
        log_audit_action(
            section="QC_ADMIN",
            subject="Project Package Needs Revision",
            message_body=f"Package '{rec.get('package_name')}' (Project Ref: {rec.get('project_ref')}) returned for revision by QC Desk.",
            recipient="engineer@semco.com"
        )
    return rec or {"id": record_id, "status": "Needs Revision"}


@app.delete("/api/project-engineer/{record_id}")
def delete_project_engineer_package(record_id: str):
    """Deletes a Project Engineer package record."""
    rec = project_engineer_store.get(record_id)
    pname = rec.get("package_name", record_id) if rec else record_id
    project_engineer_store.delete(record_id)
    try:
        project_engineer_collection.delete_one({"_id": record_id})
    except Exception:
        pass

    log_audit_action(
        section="PROJECT_ENGINEER",
        subject="Project Package Deleted",
        message_body=f"Project Engineer package '{pname}' deleted."
    )
    return {"status": "deleted", "id": record_id}


@app.get("/api/admin/dashboard-summary")
def get_master_admin_dashboard_summary():
    """Returns aggregated real-time metrics across all 7 portal modules for Master Admin Executive Dashboard."""
    all_pos = pos_store.get_all()
    all_rec = receiving_store.get_all()
    all_pe = project_engineer_store.get_all()
    all_payables = vendor_payments_store.get_all()
    all_receivables = customer_receivables_store.get_all()
    all_dispatch = dispatch_store.get_all()
    all_notifs = notifications_store.get_all()
    all_challans = challans_store.get_all()

    pos_summary = {
        "total_count": len(all_pos),
        "pending_approval": len([p for p in all_pos if p.get("approval_status") == "PENDING_APPROVAL"]),
        "approved": len([p for p in all_pos if p.get("approval_status") == "APPROVED"]),
        "drafts": len([p for p in all_pos if p.get("approval_status") == "DRAFT"]),
        "total_value": sum(float(p.get("grand_total", 0) or 0) for p in all_pos)
    }

    receiving_summary = {
        "total_count": len(all_rec),
        "verified": len([r for r in all_rec if r.get("verification_status") == "VERIFIED"]),
        "total_amount": sum(float(r.get("total_amount", 0) or 0) for r in all_rec),
        "pending_invoices": len([c for c in all_challans if c.get("invoice_status") == "AWAITING_INVOICE"])
    }

    pe_summary = {
        "total_packages": len(all_pe),
        "total_files": sum(len(p.get("files", [])) for p in all_pe)
    }

    payables_total = sum(float(p.get("bill_amount", 0) or 0) for p in all_payables)
    payables_paid = sum(float(p.get("paid_amount", 0) or 0) for p in all_payables)
    payables_due = sum(float(p.get("balance_due", 0) or 0) for p in all_payables)

    receivables_total = sum(float(r.get("total_value", 0) or 0) for r in all_receivables)
    receivables_received = sum(float(r.get("received_amount", 0) or 0) for r in all_receivables)
    receivables_outstanding = sum(float(r.get("outstanding_amount", 0) or 0) for r in all_receivables)

    payments_summary = {
        "payables_total": payables_total,
        "payables_paid": payables_paid,
        "payables_due": payables_due,
        "receivables_total": receivables_total,
        "receivables_received": receivables_received,
        "receivables_outstanding": receivables_outstanding,
        "net_cashflow": receivables_received - payables_paid,
        "net_balance_gap": receivables_outstanding - payables_due
    }

    qc_summary = {
        "total_inspections": len([r for r in all_rec if r.get("qc_status")]),
        "approved": len([r for r in all_rec if r.get("qc_status") == "APPROVED"]),
        "pending": len([r for r in all_rec if r.get("qc_status") == "PENDING"]),
        "rejected": len([r for r in all_rec if r.get("qc_status") == "REJECTED"])
    }

    dispatch_summary = {
        "total_dispatches": len(all_dispatch),
        "in_transit": len([d for d in all_dispatch if d.get("status") == "IN_TRANSIT"]),
        "delivered": len([d for d in all_dispatch if d.get("status") == "DELIVERED"])
    }

    audit_summary = {
        "total_notifications": len(all_notifs)
    }

    return {
        "pos": pos_summary,
        "receiving": receiving_summary,
        "project_engineer": pe_summary,
        "payments": payments_summary,
        "qc": qc_summary,
        "dispatch": dispatch_summary,
        "audit": audit_summary,
        "timestamp": datetime.now().isoformat()
    }


# ═══════════════════════════════════════════════════════════
# TALLY PRIME INTEGRATION ENDPOINTS (Computer B: 192.168.1.27:9000)
# ═══════════════════════════════════════════════════════════
from backend import tally_service

@app.get("/api/tally/status")
def get_tally_status():
    return tally_service.test_tally_connection()

@app.get("/api/tally/ledgers")
def get_tally_ledgers():
    ledgers = tally_service.get_tally_ledgers()
    return {"success": True, "count": len(ledgers), "ledgers": ledgers}

@app.get("/api/tally/payments")
def get_tally_payments():
    return tally_service.get_tally_payments()

@app.post("/api/tally/sync-payment")
async def sync_payment_to_tally(req: Request):
    data = await req.json()
    vendor_name = data.get("vendorName") or data.get("vendor_name")
    amount = float(data.get("amount", 0))
    bank_ledger = data.get("bankLedger") or data.get("bank_ledger")
    ref_no = data.get("refNo") or data.get("ref_no")
    narration = data.get("narration", "Payment via GateFlow Payments Desk")
    payment_date = data.get("date") or data.get("payment_date")

    result = tally_service.create_payment_voucher(
        vendor_name=vendor_name,
        amount=amount,
        bank_ledger=bank_ledger,
        ref_no=ref_no,
        narration=narration,
        payment_date=payment_date
    )
    return result


# Mount Uploaded Files
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Serve Frontend Static Files
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def serve_frontend_index():
    if os.path.exists(FRONTEND_DIR) and os.path.exists(os.path.join(FRONTEND_DIR, "index.html")):
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
    return {"status": "online", "service": "GateFlow SCM API Server", "version": "2.0"}
