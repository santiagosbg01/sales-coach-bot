"""Create admin user."""
import sys
sys.path.insert(0, '..')

from models import SessionLocal, User, UserRole, UserStatus
from dashboard_app.auth import hash_password

def create_admin(name: str, email: str, password: str):
    """Create an admin user."""
    db = SessionLocal()
    
    try:
        # Check if user exists
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"❌ User with email {email} already exists")
            return
        
        # Create admin
        admin = User(
            name=name,
            email=email,
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
            password_hash=hash_password(password)
        )
        
        db.add(admin)
        db.commit()
        
        print(f"✅ Admin user created successfully!")
        print(f"   Email: {email}")
        print(f"   Name: {name}")
        print(f"   Password: {password}")
        print(f"\n⚠️  Please change the password after first login.")
    
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python create_admin.py <name> <email> <password>")
        print("Example: python create_admin.py 'Admin User' admin@example.com admin123")
        sys.exit(1)
    
    name = sys.argv[1]
    email = sys.argv[2]
    password = sys.argv[3]
    
    create_admin(name, email, password)
