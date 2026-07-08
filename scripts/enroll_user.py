"""Enroll a new sales rep."""
import sys
sys.path.insert(0, '..')

from models import SessionLocal, User, ChannelIdentity, UserRole, UserStatus

def enroll_user(
    name: str,
    email: str,
    telegram_user_id: str,
    telegram_username: str = None,
    manager_id: int = None,
    team_id: int = None
):
    """Enroll a new rep."""
    db = SessionLocal()
    
    try:
        # Check if user exists
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"❌ User with email {email} already exists")
            return
        
        # Create user
        user = User(
            name=name,
            email=email,
            role=UserRole.REP,
            status=UserStatus.ACTIVE,
            manager_id=manager_id,
            team_id=team_id
        )
        
        db.add(user)
        db.flush()
        
        # Create channel identity
        identity = ChannelIdentity(
            user_id=user.id,
            channel="telegram",
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username
        )
        
        db.add(identity)
        db.commit()
        
        print(f"✅ User enrolled successfully!")
        print(f"   Name: {name}")
        print(f"   Email: {email}")
        print(f"   Telegram ID: {telegram_user_id}")
        print(f"\n📱 User can now start training with /start command in Telegram")
    
    except Exception as e:
        db.rollback()
        print(f"❌ Error enrolling user: {e}")
    
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python enroll_user.py <name> <email> <telegram_user_id> [telegram_username]")
        print("Example: python enroll_user.py 'John Doe' john@example.com 123456789 johndoe")
        sys.exit(1)
    
    name = sys.argv[1]
    email = sys.argv[2]
    telegram_user_id = sys.argv[3]
    telegram_username = sys.argv[4] if len(sys.argv) > 4 else None
    
    enroll_user(name, email, telegram_user_id, telegram_username)
