"""
Initialize database on app startup.
Run by docker-compose command.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import init_db, test_db_connection
import time

def main():
    print("\n" + "="*60)
    print("DecisionLedger - Database Initialization")
    print("="*60)
    
    # Wait for Postgres to be ready
    print("\n⏳ Waiting for database to be ready...")
    max_retries = 30
    for attempt in range(max_retries):
        if test_db_connection():
            print("✓ Database is ready!")
            break
        print(f"  Attempt {attempt + 1}/{max_retries}...", end="\r", flush=True)
        time.sleep(1)
    else:
        print("✗ Database failed to start!")
        sys.exit(1)
    
    # Initialize schema
    try:
        init_db()
        print("✓ Database schema initialized successfully!")
    except Exception as e:
        print(f"✗ Database initialization failed: {e}")
        sys.exit(1)
    
    # Optional: Seed data on first run
    print("\n🌱 Checking if data seeding is needed...")
    try:
        from app.database import SessionLocal
        from app.models import Proposal
        db = SessionLocal()
        
        proposal_count = db.query(Proposal).count()
        db.close()
        
        if proposal_count == 0:
            print("  No proposals found. Running seed script...")
            os.system("python scripts/seed_data.py")
        else:
            print(f"  ✓ Database already has {proposal_count} proposals (skipping seed)")
    except Exception as e:
        print(f"  ⚠ Could not check seeding status: {e}")
    
    print("\n" + "="*60)
    print("✓ Initialization complete!")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()