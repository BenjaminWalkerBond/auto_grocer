# PostgreSQL Installation Guide for WSL

## Current Status
✗ PostgreSQL is not installed in your WSL environment.

## Option 1: Install PostgreSQL in WSL (Recommended)

### Step 1: Install PostgreSQL
```bash
# Update package lists
sudo apt update

# Install PostgreSQL
sudo apt install postgresql postgresql-contrib

# Check if it's running
sudo service postgresql status

# Start PostgreSQL if not running
sudo service postgresql start
```

### Step 2: Create Database and User
```bash
# Switch to postgres user
sudo -u postgres psql

# In PostgreSQL prompt, run these commands:
CREATE DATABASE auto_grocier;
CREATE USER grocier_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE auto_grocier TO grocier_user;

# Grant schema privileges (for PostgreSQL 15+)
\c auto_grocier
GRANT ALL ON SCHEMA public TO grocier_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO grocier_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO grocier_user;

# Exit PostgreSQL
\q
```

### Step 3: Update config.txt
Update your `config.txt` file:
```
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=auto_grocier
DATABASE_USER=grocier_user
DATABASE_PASSWORD=your_secure_password
```

### Step 4: Test Connection
```bash
cd /mnt/c/Users/benbo/OneDrive/Desktop/Development/GitHub/Python/auto_grocier
uv run python database/test_connection.py
```

---

## Option 2: Use Docker PostgreSQL (Alternative)

If you prefer using Docker:

```bash
# Install Docker if not installed
# Then run PostgreSQL container
docker run --name auto_grocier_db \
  -e POSTGRES_DB=auto_grocier \
  -e POSTGRES_USER=grocier_user \
  -e POSTGRES_PASSWORD=your_password \
  -p 5432:5432 \
  -d postgres:15

# Update config.txt with same credentials
```

---

## Option 3: Install PostgreSQL on Windows (Less Recommended)

If you want to use Windows PostgreSQL:

1. Download from: https://www.postgresql.org/download/windows/
2. Install PostgreSQL
3. Update config.txt with `DATABASE_HOST=localhost` or your Windows IP
4. May need to configure PostgreSQL to accept connections from WSL

---

## Quick Install Script (Option 1 - Automated)

Save this as `install_postgres.sh` and run: `bash install_postgres.sh`

```bash
#!/bin/bash

echo "Installing PostgreSQL in WSL..."
sudo apt update
sudo apt install -y postgresql postgresql-contrib

echo "Starting PostgreSQL..."
sudo service postgresql start

echo "Creating database and user..."
sudo -u postgres psql <<EOF
CREATE DATABASE auto_grocier;
CREATE USER grocier_user WITH PASSWORD 'grocier_password_123';
GRANT ALL PRIVILEGES ON DATABASE auto_grocier TO grocier_user;
\c auto_grocier
GRANT ALL ON SCHEMA public TO grocier_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO grocier_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO grocier_user;
EOF

echo "PostgreSQL setup complete!"
echo ""
echo "Update your config.txt with:"
echo "DATABASE_PASSWORD=grocier_password_123"
```

---

## Troubleshooting

### PostgreSQL not starting?
```bash
# Check logs
sudo tail -f /var/log/postgresql/postgresql-*-main.log

# Restart service
sudo service postgresql restart
```

### Can't connect?
```bash
# Check if PostgreSQL is listening
sudo netstat -plnt | grep 5432

# Test connection manually
psql -h localhost -U grocier_user -d auto_grocier
```

### Permission issues?
```bash
# Grant all permissions again
sudo -u postgres psql -d auto_grocier <<EOF
GRANT ALL ON SCHEMA public TO grocier_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO grocier_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO grocier_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO grocier_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO grocier_user;
EOF
```

---

## Recommended: Option 1 (WSL Installation)

Run these commands to get started:

```bash
# 1. Install PostgreSQL
sudo apt update && sudo apt install -y postgresql postgresql-contrib

# 2. Start PostgreSQL
sudo service postgresql start

# 3. Setup database (will prompt for your sudo password)
sudo -u postgres psql -c "CREATE DATABASE auto_grocier;"
sudo -u postgres psql -c "CREATE USER grocier_user WITH PASSWORD 'grocier_pass_123';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE auto_grocier TO grocier_user;"
sudo -u postgres psql -d auto_grocier -c "GRANT ALL ON SCHEMA public TO grocier_user;"

# 4. Test it
python database/test_connection.py
```

Don't forget to update `DATABASE_PASSWORD=grocier_pass_123` in config.txt!
