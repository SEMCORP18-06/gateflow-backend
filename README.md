# GateFlow SCM — Backend API Server

GateFlow SCM Backend is a high-performance **FastAPI** application for Receival, Dispatch, OCR Document Processing, QC Inspections, Payment Reminders, and Tri-Party Dispatch Management.

---

## 🌟 Key Features

- **FastAPI Core Engine**: Async RESTful API endpoints with CORS support, dynamic error handling, and interactive OpenAPI docs (`/docs`).
- **Document OCR Engine**: Extraction of invoice and delivery challan metadata (Invoice #, Vendor Name, Dates, Line Items) with pytesseract fallback heuristics.
- **QC Verification & Approval Workflow**: Integrated inspection lifecycle for receiving records, project engineer packages, and dispatch cycles.
- **Tri-Party Dispatch Management**: Orchestrates supplier details, driver SMS alerts, client email notifications, and dispatch tracking timelines.
- **APScheduler Payment Scanner**: Automated daily background scheduler scanning overdue payables and firing email/SMS alerts.
- **Multi-Format Exporters**: Dynamic generation of `.xlsx`, `.csv`, and printable `.pdf` reports via ReportLab and OpenPyXL.
- **MongoDB Atlas & Persistent Store**: Dual storage adapter supporting MongoDB Atlas cluster and local JSON file persistence.

---

## 🛠️ Repository Structure

```
gateflow-backend/
├── backend/
│   ├── app.py                 # FastAPI endpoints & route handlers
│   ├── database.py            # MongoDB Atlas / SQLite connection & schemas
│   ├── ocr_engine.py          # Metadata extraction & OCR engine
│   ├── notifications.py       # Pluggable Email & SMS notification service
│   ├── scheduler.py           # APScheduler background payment scanner
│   ├── exporter.py            # PDF, Excel, and CSV export modules
│   ├── persistent_store.py    # Local JSON persistent store wrappers
│   ├── seed_data.py           # Database initial seeding
│   ├── clear_all_data.py      # Admin data cleanup utility
│   └── data/                  # Local initial JSON datasets
├── tests/
│   ├── test_gateflow.py       # API unit & integration test suite
│   └── test_mongo.py          # MongoDB connectivity & query tests
├── run.py                     # Server entry point script
├── requirements.txt           # Python package dependencies
└── README.md                  # Technical documentation
```

---

## 💻 Local Setup & Execution

### 1. Prerequisites
- Python 3.9+ installed.

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Start API Server
```bash
python run.py
```
Or run directly using Uvicorn:
```bash
uvicorn backend.app:app --host 0.0.0.0 --port 5000 --reload
```

### 4. Interactive API Documentation
Access Swagger UI and ReDoc in your browser:
- Swagger Docs: `http://localhost:5000/docs`
- ReDoc: `http://localhost:5000/redoc`

---

## 🧪 Automated Testing

Execute full test suite using `pytest`:
```bash
pytest tests/
```
