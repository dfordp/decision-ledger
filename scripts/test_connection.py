import psycopg2
import sys

def test_database_connection():
    """Test that database is accessible and pgvector is enabled"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="decisionledger",
            user="postgres",
            password="postgres"
        )
        
        cursor = conn.cursor()
        
        # Test pgvector extension
        cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
        result = cursor.fetchone()
        
        if result:
            print("✓ Database connected successfully")
            print("✓ pgvector extension enabled")
        else:
            print("✗ pgvector extension not found")
            sys.exit(1)
        
        # Test tables exist
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        expected_tables = [
            'vendors', 'evaluation_dimension', 'vendor_policy',
            'proposals', 'proposal_decisions', 'tenders', 'tender_requirements'
        ]
        
        print(f"\n✓ Found {len(tables)} tables:")
        for table in tables:
            print(f"  - {table}")
        
        missing = set(expected_tables) - set(tables)
        if missing:
            print(f"\n✗ Missing tables: {missing}")
            sys.exit(1)
        
        cursor.close()
        conn.close()
        
        print("\n✓ All checks passed!")
        
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_database_connection()