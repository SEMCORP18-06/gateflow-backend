"""
Tally Prime Integration Module for GateFlow Payments Desk
Connects to Tally Prime on Computer B (IP: 192.168.1.27:9000)
"""

import os
import re
import urllib.request
import urllib.error
from datetime import datetime

TALLY_HOST = os.getenv("TALLY_HOST", "192.168.1.27")
TALLY_PORT = os.getenv("TALLY_PORT", "9000")
TALLY_URL = f"http://{TALLY_HOST}:{TALLY_PORT}"
DEFAULT_BANK_LEDGER = os.getenv("TALLY_BANK_LEDGER", "HDFC Bank")

def _send_xml(xml_payload: str, timeout: int = 5) -> str:
    req = urllib.request.Request(
        TALLY_URL,
        data=xml_payload.encode('utf-8'),
        headers={'Content-Type': 'text/xml'}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='ignore')

def test_tally_connection() -> dict:
    """Test connectivity to Tally Prime on 192.168.1.27:9000"""
    xml_request = """<ENVELOPE>
      <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
      <BODY><EXPORTDATA><REQUESTDESC><REPORTNAME>List of Accounts</REPORTNAME></REQUESTDESC></EXPORTDATA></BODY>
    </ENVELOPE>"""
    try:
        res = _send_xml(xml_request, timeout=4)
        return {
            "online": True,
            "message": f"Successfully connected to Tally Prime at {TALLY_URL}",
            "tally_url": TALLY_URL
        }
    except Exception as e:
        return {
            "online": False,
            "message": f"Could not connect to Tally at {TALLY_URL}. Error: {str(e)}",
            "tally_url": TALLY_URL
        }

def get_tally_ledgers() -> list:
    """Fetch all active Accounts/Ledgers from Tally Prime"""
    xml_request = """<ENVELOPE>
      <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
      <BODY>
        <EXPORTDATA>
          <REQUESTDESC>
            <REPORTNAME>List of Accounts</REPORTNAME>
            <STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES>
          </REQUESTDESC>
        </EXPORTDATA>
      </BODY>
    </ENVELOPE>"""
    try:
        res = _send_xml(xml_request)
        names = re.findall(r'<NAME>(.*?)</NAME>', res, re.IGNORECASE)
        cleaned = list(set([n.replace('&amp;', '&') for n in names if n]))
        return sorted(cleaned)
    except Exception as e:
        print(f"Error fetching ledgers: {e}")
        return []

def create_payment_voucher(vendor_name: str, amount: float, bank_ledger: str = None, ref_no: str = None, narration: str = "Payment via GateFlow Desk", payment_date: str = None) -> dict:
    """Create a Payment Voucher in Tally Prime"""
    if not bank_ledger:
        bank_ledger = DEFAULT_BANK_LEDGER
    if not ref_no:
        ref_no = f"PAY-{int(datetime.now().timestamp())}"
    
    date_str = datetime.now().strftime("%Y%m%d")
    if payment_date:
        try:
            d = datetime.strptime(payment_date[:10], "%Y-%m-%d")
            date_str = d.strftime("%Y%m%d")
        except Exception:
            pass

    safe_vendor = vendor_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_bank = bank_ledger.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_ref = ref_no.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    safe_narr = narration.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    xml_payload = f"""<ENVELOPE>
  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Payment" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{date_str}</DATE>
            <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{safe_ref}</VOUCHERNUMBER>
            <REFERENCE>{safe_ref}</REFERENCE>
            <NARRATION>{safe_narr}</NARRATION>

            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{safe_vendor}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>YES</ISDEEMEDPOSITIVE>
              <AMOUNT>-{amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>

            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{safe_bank}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>NO</ISDEEMEDPOSITIVE>
              <AMOUNT>{amount:.2f}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    try:
        res = _send_xml(xml_payload)
        is_created = "<CREATED>1</CREATED>" in res or "<UPDATED>1</UPDATED>" in res
        err_match = re.search(r'<LINEERROR>(.*?)</LINEERROR>', res, re.IGNORECASE)
        
        if is_created:
            return {
                "success": True,
                "ref_no": ref_no,
                "message": f"Payment voucher of ₹{amount} for '{vendor_name}' successfully created in Tally Prime."
            }
        else:
            return {
                "success": False,
                "ref_no": ref_no,
                "error": err_match.group(1) if err_match else "Tally Prime rejected the voucher creation."
            }
    except Exception as e:
        return {
            "success": False,
            "ref_no": ref_no,
            "error": f"Failed to reach Tally Prime server: {str(e)}"
        }

def get_tally_payments() -> dict:
    """Fetch payment register from Tally Prime"""
    xml_request = """<ENVELOPE>
      <HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>
      <BODY>
        <EXPORTDATA>
          <REQUESTDESC>
            <REPORTNAME>Voucher Register</REPORTNAME>
            <STATICVARIABLES>
              <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
              <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
            </STATICVARIABLES>
          </REQUESTDESC>
        </EXPORTDATA>
      </BODY>
    </ENVELOPE>"""
    try:
        res = _send_xml(xml_request)
        vouchers = re.findall(r'<VOUCHER[^>]*>([\s\S]*?)</VOUCHER>', res, re.IGNORECASE)
        payments = []
        for v in vouchers:
            date_m = re.search(r'<DATE[^>]*>(.*?)</DATE>', v, re.IGNORECASE)
            party_m = re.search(r'<PARTYLEDGERNAME[^>]*>(.*?)</PARTYLEDGERNAME>', v, re.IGNORECASE)
            num_m = re.search(r'<VOUCHERNUMBER[^>]*>(.*?)</VOUCHERNUMBER>', v, re.IGNORECASE)
            amt_m = re.search(r'<AMOUNT[^>]*>(.*?)</AMOUNT>', v, re.IGNORECASE)
            narr_m = re.search(r'<NARRATION[^>]*>(.*?)</NARRATION>', v, re.IGNORECASE)

            raw_d = date_m.group(1) if date_m else ""
            fmt_d = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:8]}" if len(raw_d) == 8 else raw_d

            payments.append({
                "date": fmt_d,
                "voucher_number": num_m.group(1) if num_m else "N/A",
                "party_name": party_m.group(1).replace('&amp;', '&') if party_m else "Unknown",
                "amount": abs(float(amt_m.group(1))) if amt_m else 0.0,
                "narration": narr_m.group(1).replace('&amp;', '&') if narr_m else ""
            })
        return {"success": True, "count": len(payments), "payments": payments}
    except Exception as e:
        return {"success": False, "error": str(e), "payments": []}
