import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from backend.persistent_store import receiving_store, dispatch_store, notifications_store
from backend.notifications import send_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GateFlowScheduler")

scheduler = AsyncIOScheduler()


def check_payment_calendar_job():
    """
    Scans unpaid receiving invoices and pending dispatch collections past or nearing due date within 7 days
    and sends summary email reminders to Admin & logs audit notifications.
    """
    logger.info("Executing daily Payment & Collection Calendar background scan...")
    try:
        raw_receiving = [r for r in receiving_store.get_all() if r.get("status") != "Paid"]
        raw_dispatches = [d for d in dispatch_store.get_all() if d.get("collection_status") != "Collected"]
        today = datetime.now().date()
        
        overdue_payables = []
        upcoming_payables = []
        overdue_collections = []
        upcoming_collections = []

        for r in raw_receiving:
            due_str = r.get("due_date")
            if not due_str:
                continue
            try:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            days_diff = (due_dt - today).days

            if days_diff < 0:
                overdue_payables.append(r)
            elif 0 <= days_diff <= 7:
                upcoming_payables.append(r)

        for d in raw_dispatches:
            due_str = d.get("collection_due_date")
            if not due_str:
                continue
            try:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            days_diff = (due_dt - today).days

            if days_diff < 0:
                overdue_collections.append(d)
            elif 0 <= days_diff <= 7:
                upcoming_collections.append(d)

        if overdue_payables or upcoming_payables or overdue_collections or upcoming_collections:
            summary = f"GateFlow Financial Calendar Summary ({today.strftime('%Y-%m-%d')}):\n\n"
            
            summary += f"💳 VENDOR PAYABLES (Receiving):\n"
            summary += f"- Overdue Payables ({len(overdue_payables)}):\n"
            for item in overdue_payables:
                summary += f"  • {item.get('invoice_number')} ({item.get('vendor_name')}) - Amount: ₹{float(item.get('total_amount', 0)):,.2f} - Due: {item.get('due_date')}\n"
            summary += f"- Upcoming Payables ({len(upcoming_payables)}):\n"
            for item in upcoming_payables:
                summary += f"  • {item.get('invoice_number')} ({item.get('vendor_name')}) - Amount: ₹{float(item.get('total_amount', 0)):,.2f} - Due: {item.get('due_date')}\n"

            summary += f"\n💰 CLIENT COLLECTIONS (Dispatch):\n"
            summary += f"- Overdue Collections ({len(overdue_collections)}):\n"
            for item in overdue_collections:
                summary += f"  • {item.get('dispatch_number')} ({item.get('client_name')}) - Amount: ₹{float(item.get('invoice_amount', 0)):,.2f} - Due: {item.get('collection_due_date')}\n"
            summary += f"- Upcoming Collections ({len(upcoming_collections)}):\n"
            for item in upcoming_collections:
                summary += f"  • {item.get('dispatch_number')} ({item.get('client_name')}) - Amount: ₹{float(item.get('invoice_amount', 0)):,.2f} - Due: {item.get('collection_due_date')}\n"

            send_email(
                recipient="admin@semco.com",
                subject=f"[FINANCIAL CALENDAR AUDIT] {len(overdue_payables) + len(overdue_collections)} Actionable Items Needing Attention",
                message_body=summary
            )

            # Log Audit action for Receiving payables
            if overdue_payables or upcoming_payables:
                nid = f"notif_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                notifications_store.insert(nid, {
                    "id": nid,
                    "recipient": "receiving-desk@semco.com",
                    "subject": "Automated Financial Audit",
                    "message_body": f"Daily audit completed: {len(overdue_payables)} overdue invoice(s), {len(upcoming_payables)} upcoming invoice(s) in 7 days.",
                    "section": "RECEIVING",
                    "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "created_at": datetime.now().isoformat()
                })

            logger.info("Payment & Collection Calendar scan complete. Email sent to admin.")

    except Exception as e:
        logger.error(f"Error in payment calendar job: {e}")


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(check_payment_calendar_job, 'cron', hour=8, minute=0, id="check_payment_calendar_job", replace_existing=True)
        scheduler.start()
        logger.info("APScheduler started successfully for GateFlow.")
