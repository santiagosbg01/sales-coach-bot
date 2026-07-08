"""Background scheduler for automated tasks."""
import sys
sys.path.insert(0, '..')

from apscheduler.schedulers.blocking import BlockingScheduler
from models import SessionLocal
from services import AlertSystem
from datetime import datetime

def check_alerts_job():
    """Job to check alerts."""
    print(f"[{datetime.now()}] Running alert checks...")
    db = SessionLocal()
    
    try:
        alert_system = AlertSystem(db)
        alerts = alert_system.check_all_alerts()
        print(f"  Found {len(alerts)} new alerts")
    except Exception as e:
        print(f"  Error: {e}")
    finally:
        db.close()


def main():
    """Start scheduler."""
    scheduler = BlockingScheduler()
    
    # Run alert checks daily at 9 AM
    scheduler.add_job(check_alerts_job, 'cron', hour=9, minute=0)
    
    print("🕐 Scheduler started")
    print("   - Alert checks: Daily at 9:00 AM (AlertSystem legado; el bot usa proactive_sender)")
    print("\nPress Ctrl+C to exit")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nScheduler stopped")


if __name__ == "__main__":
    main()
