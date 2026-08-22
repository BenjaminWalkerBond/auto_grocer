"""
Initialize the database schema.
Creates all tables using SQLAlchemy models.
"""
import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_grocer.database.db_config import DatabaseConfig
from auto_grocer.database.db_connection import engine
from auto_grocer.database.models import Base


def init_database():
    """Initialize database schema by creating all tables"""
    try:
        print("=" * 60)
        print("Database Initialization")
        print("=" * 60)

        # Print configuration
        DatabaseConfig.print_config()
        print()

        # Create all tables
        print("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        print("✓ All tables created successfully!")
        print()

        # List created tables
        print("Created tables:")
        for table_name in Base.metadata.tables.keys():
            print(f"  - {table_name}")

        print()
        print("=" * 60)
        print("Database initialization complete!")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"✗ Error initializing database: {e}")
        return False


if __name__ == '__main__':
    success = init_database()
    sys.exit(0 if success else 1)
