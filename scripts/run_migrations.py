#!/usr/bin/env python
"""
Run all SQL migrations from the migrations/ directory in order.
"""

import sys
import os
import glob
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import execute_query

def run_migrations():
    """Execute all migrations in order"""
    migrations_dir = Path('migrations')
    
    if not migrations_dir.exists():
        print(f"✗ Migrations directory not found: {migrations_dir}")
        sys.exit(1)
    
    # Get all SQL files and sort by numeric prefix
    migration_files = sorted(glob.glob(str(migrations_dir / '*.sql')))
    
    if not migration_files:
        print(f"✗ No migration files found in {migrations_dir}")
        sys.exit(1)
    
    print(f"Found {len(migration_files)} migration(s)")
    print("=" * 70)
    
    for migration_file in migration_files:
        filename = os.path.basename(migration_file)
        print(f"\nRunning: {filename}")
        
        try:
            with open(migration_file, 'r') as f:
                sql_content = f.read()
            
            # Split by semicolon and execute each statement
            statements = [s.strip() for s in sql_content.split(';') if s.strip()]
            
            for statement in statements:
                execute_query(statement)
            
            print(f"✓ {filename} completed successfully")
        
        except Exception as e:
            print(f"✗ {filename} failed: {e}")
            sys.exit(1)
    
    print("\n" + "=" * 70)
    print("✓ All migrations completed successfully")

if __name__ == "__main__":
    run_migrations()
