"""
Database connection and query helpers for DecisionLedger.
Uses psycopg2 with connection pooling for PostgreSQL + pgvector.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import os
from dotenv import load_dotenv

load_dotenv()

# Connection pool (singleton pattern)
_pool = None

def get_connection_pool():
    """Get or create connection pool"""
    global _pool
    if _pool is None:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/decisionledger"
        )
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=database_url
        )
    return _pool

@contextmanager
def get_connection():
    """Context manager for database connections"""
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)

def execute_query(query: str, params: tuple = None) -> None:
    """Execute a query without returning results (INSERT, UPDATE, DELETE)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        cursor.close()

def fetch_one(query: str, params: tuple = None) -> Optional[Dict[str, Any]]:
    """Fetch a single row as a dictionary"""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, params)
        result = cursor.fetchone()
        cursor.close()
        return dict(result) if result else None

def fetch_all(query: str, params: tuple = None) -> List[Dict[str, Any]]:
    """Fetch all rows as a list of dictionaries"""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in results]

def fetch_one_value(query: str, params: tuple = None) -> Any:
    """Fetch a single value from a query"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchone()
        cursor.close()
        return result[0] if result else None

def insert_and_return_id(query: str, params: tuple = None) -> int:
    """Execute INSERT and return the generated ID"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query + " RETURNING id", params)
        result_id = cursor.fetchone()[0]
        cursor.close()
        return result_id

def vector_search(
    table: str,
    embedding_column: str,
    query_embedding: List[float],
    limit: int = 5,
    additional_conditions: str = "",
    params: tuple = None
) -> List[Dict[str, Any]]:
    """
    Perform vector similarity search using cosine distance.
    
    Args:
        table: Table name to search
        embedding_column: Column name containing embeddings
        query_embedding: Vector to search for
        limit: Number of results to return
        additional_conditions: Additional WHERE clauses (e.g., "AND dimension_id = %s")
        params: Parameters for additional conditions
    
    Returns:
        List of rows with similarity scores
    """
    # Convert embedding list to pgvector format
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
    
    query = f"""
        SELECT *,
               1 - ({embedding_column} <=> %s::vector) as similarity
        FROM {table}
        WHERE {embedding_column} IS NOT NULL
        {additional_conditions}
        ORDER BY {embedding_column} <=> %s::vector
        LIMIT %s
    """
    
    # Build parameter tuple
    query_params = [embedding_str, embedding_str, limit]
    if params:
        query_params = [embedding_str] + list(params) + [embedding_str, limit]
    
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, tuple(query_params))
        results = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in results]

def get_dimension_id(dimension_key: str) -> Optional[int]:
    """Get dimension ID from key"""
    query = "SELECT id FROM evaluation_dimension WHERE key = %s"
    return fetch_one_value(query, (dimension_key,))

def get_vendor_id() -> int:
    """Get the single vendor ID (POC assumes one vendor)"""
    vendor_id = fetch_one_value("SELECT id FROM vendors LIMIT 1")
    if not vendor_id:
        raise ValueError("No vendor found in database. Run seed script first.")
    return vendor_id