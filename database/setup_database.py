"""
Complete database setup script.
Initializes database schema and seeds with initial data.
"""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.init_db import init_database
from database.seed_tags import seed_tags
from database.db_connection import test_connection


def setup_database():
    """Complete database setup"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 15 + "AUTO GROCIER DATABASE SETUP" + " " * 15 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    # Step 1: Test connection
    print("Step 1: Testing database connection...")
    if not test_connection():
        print("\n✗ Database connection failed!")
        print("Please check your database configuration in .env")
        print("Make sure PostgreSQL is running and credentials are correct.")
        return False
    print()
    
    # Step 2: Initialize schema
    print("Step 2: Initializing database schema...")
    if not init_database():
        print("\n✗ Database initialization failed!")
        return False
    print()
    
    # Step 3: Seed tags
    print("Step 3: Seeding initial tags...")
    if not seed_tags():
        print("\n✗ Tag seeding failed!")
        return False
    print()
    
    # Success!
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 12 + "DATABASE SETUP COMPLETE! ✓" + " " * 18 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    print("Your database is ready to use!")
    print()
    print("Next steps:")
    print("  1. Run test_database.py to verify everything works")
    print("  2. Start using the ingredient repositories in your code")
    print()
    
    return True


if __name__ == '__main__':
    success = setup_database()
    sys.exit(0 if success else 1)
