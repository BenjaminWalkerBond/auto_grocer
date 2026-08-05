"""
Database connection module.
Manages SQLAlchemy engine and session creation.
"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .db_config import DatabaseConfig

# Create database engine
engine: Engine | None
try:
    DATABASE_URL = DatabaseConfig.get_database_url()
    engine = create_engine(
        DATABASE_URL,
        echo=False,  # Set to True for SQL query logging
        pool_pre_ping=True,  # Verify connections before using them
        pool_size=5,
        max_overflow=10
    )
    print("✓ Database engine created successfully")
except Exception as e:
    print(f"✗ Error creating database engine: {e}")
    engine = None

# Create session factory
SessionLocal: sessionmaker[Session] | None
if engine:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
else:
    SessionLocal = None


def get_db() -> Iterator[Session]:
    """
    Get a database session.
    Use this as a context manager or with dependency injection.

    Example:
        with get_db() as db:
            # Use db session here
            pass
    """
    if SessionLocal is None:
        raise Exception("Database session factory not initialized. Check database configuration.")

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """
    Get a database session (non-generator version).
    Remember to close the session when done.

    Example:
        db = get_db_session()
        try:
            # Use db session here
            pass
        finally:
            db.close()
    """
    if SessionLocal is None:
        raise Exception("Database session factory not initialized. Check database configuration.")

    return SessionLocal()


def test_connection():
    """Test the database connection"""
    try:
        from sqlalchemy import text
        db = get_db_session()
        db.execute(text("SELECT 1"))
        db.close()
        print("✓ Database connection test successful")
        return True
    except Exception as e:
        print(f"✗ Database connection test failed: {e}")
        return False
