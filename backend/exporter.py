import csv
import io
import json
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


def export_to_csv(records: list) -> str:
    """Generates CSV string from receiving or dispatch records."""
    if not records:
        return ""
    
    # Collect all unique headers across all records
    headers_set = set()
    for r in records:
        headers_set.update(r.keys())
    headers = sorted(list(headers_set))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for row in records:
        clean_row = {}
        for k in headers:
            v = row.get(k, "")
            if isinstance(v, (dict, list)):
                clean_row[k] = json.dumps(v)
            else:
                clean_row[k] = str(v)
        writer.writerow(clean_row)
    
    return output.getvalue()


def export_to_xlsx(records: list) -> bytes:
    """Generates Excel (.xlsx) file bytes from receiving or dispatch records."""
    if not records:
        df = pd.DataFrame()
    else:
        clean_records = []
        for r in records:
            row = r.copy()
            for k, v in row.items():
                if isinstance(v, (dict, list)):
                    row[k] = json.dumps(v)
            clean_records.append(row)
        df = pd.DataFrame(clean_records)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name="GateFlow_Export")
    return output.getvalue()


def export_to_pdf(title: str, records: list) -> bytes:
    """Generates a PDF summary document."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#003B96'),
        spaceAfter=12
    )
    
    elements = [
        Paragraph(f"SEMCO GateFlow SCM — {title}", title_style),
        Spacer(1, 10)
    ]
    
    if not records:
        elements.append(Paragraph("No records found.", styles['Normal']))
    else:
        sample = records[0]
        cols = [k for k in sample.keys() if k in ['invoice_number', 'vendor_name', 'due_date', 'total_amount', 'status', 'dispatch_number', 'client_name', 'driver_name']]
        
        if not cols:
            cols = list(sample.keys())[:5]

        table_data = [[col.replace('_', ' ').title() for col in cols]]
        for r in records:
            row_data = [str(r.get(col, '')) for col in cols]
            table_data.append(row_data)
        
        t = Table(table_data, colWidths=None)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#003B96')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFD')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        elements.append(t)
        
    doc.build(elements)
    return buffer.getvalue()
