"""
Simple database connection test.
Tests if we can connect to PostgreSQL with the configured credentials.
"""
import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("DATABASE CONNECTION TEST")
print("=" * 60)
print()

# Step 1: Check configuration
print("Step 1: Checking configuration...")
try:
    from auto_grocier.database.db_config import DatabaseConfig
    DatabaseConfig.print_config()
    print("✓ Configuration loaded")
except Exception as e:
    print(f"✗ Configuration error: {e}")
    sys.exit(1)

print()

# Step 2: Test connection
print("Step 2: Testing database connection...")
try:
    from auto_grocier.database.db_connection import get_db_session, test_connection

    if test_connection():
        print("✓ Connection successful!")
        print()

        # Step 3: Try a simple query
        print("Step 3: Testing query execution...")
        try:
            from sqlalchemy import text
            db = get_db_session()
            result = db.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            print(f"✓ PostgreSQL version: {version}")
            db.close()
        except Exception as e:
            print(f"✗ Query failed: {e}")
            sys.exit(1)

        print()
        print("=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        print()
        print("Your database is ready to use!")
        print("Next steps:")
        print("  1. Run: python database/setup_database.py")
        print("  2. Then: python database/test_database.py")

    else:
        print("✗ Connection failed!")
        print()
        print("Troubleshooting:")
        print("  1. Is PostgreSQL running?")
        print("  2. Does the database exist?")
        print("  3. Are credentials in .env correct?")
        print("  4. Check DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, DATABASE_USER, DATABASE_PASSWORD")
        sys.exit(1)

except Exception as e:
    print(f"✗ Connection test failed: {e}")
    print()
    print("Common issues:")
    print("  - PostgreSQL not installed or not running")
    print("  - Database 'auto_grocier' doesn't exist")
    print("  - Wrong credentials in .env")
    print("  - psycopg2-binary not installed (run: pip install psycopg2-binary)")
    import traceback
    traceback.print_exc()
    sys.exit(1)
