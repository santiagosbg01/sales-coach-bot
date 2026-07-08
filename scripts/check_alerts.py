"""Run alert checks and display results."""
import sys
sys.path.insert(0, '..')

from models import SessionLocal
from services import AlertSystem

def run_alert_checks():
    """Run all alert checks."""
    db = SessionLocal()
    
    try:
        alert_system = AlertSystem(db)
        
        print("🔍 Running alert checks...")
        alerts = alert_system.check_all_alerts()
        
        if alerts:
            print(f"\n⚠️  Found {len(alerts)} new alerts:\n")
            for alert in alerts:
                severity_emoji = {
                    'info': 'ℹ️',
                    'warning': '⚠️',
                    'critical': '🚨'
                }
                emoji = severity_emoji.get(alert.severity.value, '⚠️')
                print(f"{emoji} [{alert.type.value}] {alert.title}")
                print(f"   {alert.message}\n")
        else:
            print("\n✅ No new alerts. Everything looks good!")
        
    finally:
        db.close()


if __name__ == "__main__":
    run_alert_checks()
