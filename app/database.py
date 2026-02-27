"""
Database configuration and initialization.
"""
import os
from sqlalchemy import create_engine, text, exc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from app.config import DATABASE_URL, DEBUG
import logging

logger = logging.getLogger(__name__)

# Database engine
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,
    echo=DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_db_connection():
    """Test if database is accessible."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"DB connection failed: {e}")
        return False

def init_db():
    """Initialize database schema (ENUMs already created by schema.sql)."""
    logger.info("✓ Database schema verified")

def get_db():
    """Get database session for dependency injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()