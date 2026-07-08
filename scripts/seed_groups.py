#!/usr/bin/env python3
"""Seed the 8 default groups: Farmers/Hunters × Mexico/Chile/Colombia/Peru."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import SessionLocal, Group, init_db, migrate_db

GROUPS = [
    "Farmers Mexico",
    "Farmers Chile",
    "Farmers Colombia",
    "Farmers Peru",
    "Hunters Mexico",
    "Hunters Chile",
    "Hunters Colombia",
    "Hunters Peru",
]


def main():
    init_db()
    migrate_db()
    db = SessionLocal()
    try:
        for name in GROUPS:
            existing = db.query(Group).filter(Group.name == name).first()
            if not existing:
                g = Group(name=name)
                db.add(g)
                print(f"  + {name}")
            else:
                print(f"  = {name} (exists)")
        db.commit()
        print(f"\nDone. {len(GROUPS)} groups.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
