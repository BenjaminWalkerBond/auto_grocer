#!/bin/bash
# Quick start script for database setup

echo "=========================================="
echo "Auto Grocier Database Quick Start"
echo "=========================================="
echo ""

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo "✗ PostgreSQL is not installed!"
    echo ""
    echo "Please install PostgreSQL first:"
    echo "  Ubuntu/Debian: sudo apt install postgresql postgresql-contrib"
    echo "  macOS: brew install postgresql"
    echo "  Windows: Download from https://www.postgresql.org/download/windows/"
    exit 1
fi

echo "✓ PostgreSQL is installed"
echo ""

# Check if virtual environment is activated
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

echo "✓ Virtual environment activated"
echo ""

# Install Python dependencies if needed
echo "Checking Python dependencies..."
pip list | grep -q sqlalchemy
if [ $? -ne 0 ]; then
    echo "Installing SQLAlchemy and psycopg2..."
    pip install sqlalchemy psycopg2-binary
else
    echo "✓ Dependencies already installed"
fi
echo ""

# Check if database exists
echo "Checking database configuration..."
python -c "from database.db_config import DatabaseConfig; DatabaseConfig.print_config()"
echo ""

echo "=========================================="
echo "Setup Steps:"
echo "=========================================="
echo ""
echo "1. Make sure PostgreSQL is running"
echo "2. Create database and user:"
echo "   sudo -u postgres psql"
echo "   CREATE DATABASE auto_grocier;"
echo "   CREATE USER grocier_user WITH PASSWORD 'your_password';"
echo "   GRANT ALL PRIVILEGES ON DATABASE auto_grocier TO grocier_user;"
echo "   \\q"
echo ""
echo "3. Update config.txt with your database credentials"
echo ""
echo "4. Run the setup:"
echo "   python database/setup_database.py"
echo ""
echo "5. Test it:"
echo "   python database/test_database.py"
echo ""
echo "=========================================="
