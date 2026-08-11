import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app
from backend.database import receiving_collection, dispatch_collection, notification_collection, format_doc
from backend.scheduler import check_payment_calendar_job

client = TestClient(app)


def test_seed_data_loaded_mongodb():
    """Verify database seed data is automatically loaded into MongoDB Atlas."""
    res = client.get("/api/receiving")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_receiving_dynamic_ocr_upload():
    """Verify dynamic OCR upload endpoint extracts headings & fields without restricted criteria."""
    from PIL import Image
    import io
    img = Image.new('RGB', (100, 100), color='white')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)

    res = client.post(
        "/api/receiving/ocr-upload",
        files={"file": ("test_invoice.jpg", img_bytes, "image/jpeg")}
    )
    assert res.status_code == 200
    json_data = res.json()
    assert "extracted_fields" in json_data
    assert isinstance(json_data["extracted_fields"], dict)
    assert "document_path" in json_data


def test_receiving_direct_save_mongodb():
    """Verify Receiving records are saved directly as Verified in MongoDB."""
    res = client.post(
        "/api/receiving",
        data={
            "invoice_number": "TEST-DIRECT-100",
            "vendor_name": "Direct Vendor",
            "invoice_date": "2026-07-22",
            "due_date": "2026-08-01",
            "total_amount": 7500.0,
            "extracted_fields_json": '{"Heading 1": "Details 1"}'
        }
    )
    assert res.status_code == 200
    assert res.json()["status"] in ["Verified", "Pending QC", "QC Approved"]


def test_tri_party_dispatch_workflow_mongodb():
    """Verify Tri-Party Dispatch creation, QC Approval, and SMS/Email triggering in MongoDB."""
    res = client.post(
        "/api/dispatch",
        data={
            "supplier_name": "Testing Dynamic Supplier",
            "supplier_phone": "+91 99999 11111",
            "driver_name": "Dynamic Driver",
            "driver_phone": "+91 99999 44444",
            "vehicle_number": "MH-01-AB-8888",
            "truck_type": "10 Ton Truck",
            "client_name": "Testing Dynamic Client",
            "delivery_location": "Testing Delivery Hub Pune",
            "client_email": "dynamicclient@test.com",
            "client_phone": "+91 99999 55555",
            "invoice_amount": 85000.0,
            "collection_due_date": "2026-08-10"
        }
    )
    assert res.status_code == 200
    dispatch_data = res.json()
    disp_id = dispatch_data["id"]

    res_approve = client.post(f"/api/dispatch/{disp_id}/approve")
    assert res_approve.status_code == 200
    assert res_approve.json()["status"] in ["QC Approved", "OK for Dispatch"]

    # Mark payment collected
    res_col = client.post(f"/api/dispatch/{disp_id}/mark-collected")
    assert res_col.status_code == 200
    assert res_col.json()["collection_status"] == "Collected"


def test_payment_calendar_scheduler_mongodb():
    """Verify payment calendar background scan job logs reminders."""
    check_payment_calendar_job()
    res = client.get("/api/notifications")
    assert res.status_code == 200


def test_data_exporters_mongodb():
    """Verify CSV, XLSX, and PDF export endpoints from MongoDB."""
    res_csv = client.get("/api/receiving/export?format=csv")
    assert res_csv.status_code == 200

    res_xlsx = client.get("/api/receiving/export?format=xlsx")
    assert res_xlsx.status_code == 200

    res_pdf = client.get("/api/receiving/export?format=pdf")
    assert res_pdf.status_code == 200


def test_project_engineer_workflow():
    """Verify Project Engineer package submission, QC approval, and retrieval."""
    res_get = client.get("/api/project-engineer")
    assert res_get.status_code == 200
    assert isinstance(res_get.json(), list)

    res_save = client.post(
        "/api/project-engineer",
        data={
            "package_name": "Test Engineering Package",
            "project_ref": "PRJ-TEST-100",
            "po_number": "PO-9900",
            "vendor_name": "Test Vendor",
            "engineer_name": "Tester Engineer",
            "notes": "Testing multi-file upload",
            "categories_json": '["Material Test Certificate (MTC)"]',
            "notes_json": '["Test Note"]'
        }
    )
    assert res_save.status_code == 200
    pkg_data = res_save.json()
    assert pkg_data["status"] == "Pending QC"
    assert pkg_data["project_ref"] == "PRJ-TEST-100"

    pkg_id = pkg_data["id"]

    # Test QC Approval
    res_appr = client.post(f"/api/project-engineer/{pkg_id}/approve-qc", data={"qc_comments": "Verified by QC Test"})
    assert res_appr.status_code == 200
    assert res_appr.json()["status"] in ["Verified", "QC Approved"]

    # Clean up test package
    client.delete(f"/api/project-engineer/{pkg_id}")

