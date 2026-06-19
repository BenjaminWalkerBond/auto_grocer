## Database Setup and Usage Guide

## Overview
This project uses PostgreSQL to store ingredients, recipes, and tags. The database is managed using SQLAlchemy ORM.

---

## Prerequisites

### 1. Install PostgreSQL (Windows)

PostgreSQL 15 is already installed locally on this machine at
`C:\Program Files\PostgreSQL\15` and runs as the Windows service
`postgresql-x64-15` on port **5432**.

> If you ever need to (re)install, download the installer from
> [postgresql.org](https://www.postgresql.org/download/windows/). The installer
> adds `psql.exe` under `C:\Program Files\PostgreSQL\15\bin`.

Verify the service is running (PowerShell):
```powershell
Get-Service postgresql-x64-15
```

> Note: a PostgreSQL 17 service (`postgresql-x64-17`) also exists on port
> **5433**. This project uses the **15 / 5432** instance, which matches
> `config.txt`.

### 2. Create Database and User

The repo ships an idempotent bootstrap script. From the project root, run it as
the `postgres` superuser (you'll be prompted for the postgres password):

```powershell
& 'C:\Program Files\PostgreSQL\15\bin\psql.exe' -U postgres -h localhost -p 5432 -f database/bootstrap_local.sql
```

This creates the `grocier_user` role and the `auto_grocier` database with the
correct privileges. Equivalent manual steps if you prefer doing it by hand:

```powershell
& 'C:\Program Files\PostgreSQL\15\bin\psql.exe' -U postgres -h localhost -p 5432
```
```sql
-- In the psql prompt:
CREATE USER grocier_user WITH PASSWORD 'grocier_pass_123';
CREATE DATABASE auto_grocier OWNER grocier_user;
GRANT ALL PRIVILEGES ON DATABASE auto_grocier TO grocier_user;
\q
```

---

## Configuration

Update `config.txt` with your database credentials (already set on this machine):

```
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=auto_grocier
DATABASE_USER=grocier_user
DATABASE_PASSWORD=grocier_pass_123
```

---

## Installation

### 1. Install Python Dependencies

```powershell
# Activate your virtual environment (PowerShell)
.\venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
```

> Git Bash users: use `source venv/Scripts/activate` instead.
> To run a one-off command without activating, prefix it with the venv
> interpreter: `venv\Scripts\python.exe database\setup_database.py`.

This will install:
- `sqlalchemy` - ORM for database operations
- `psycopg2-binary` - PostgreSQL adapter for Python

### 2. Initialize Database

```powershell
# Run the complete setup (recommended)
python database\setup_database.py
```

This will:
1. Test database connection
2. Create all tables (ingredients, tags, recipes, ingredient_tags)
3. Seed initial tags (cheese, fish, fruit, meat, oil, pasta, spice, tree_nut, vegetable, wine)

**OR** run steps individually:

```powershell
# Step 1: Initialize schema
python database\init_db.py

# Step 2: Seed tags
python database\seed_tags.py
```

### 3. Verify Installation

```powershell
python database\test_database.py
```

This will create sample data and test all CRUD operations.

---

## Database Schema

```
┌─────────────┐         ┌──────────────────┐         ┌──────────┐
│   recipes   │         │   ingredients    │         │   tags   │
├─────────────┤         ├──────────────────┤         ├──────────┤
│ id          │────────<│ recipe_id        │>────────│ id       │
│ url         │         │ name             │         │ name     │
│ title       │         │ amount           │         │ descrip. │
│ source_...  │         │ unit             │         │ created  │
│ created_at  │         │ created_at       │         └──────────┘
│ updated_at  │         │ updated_at       │              ▲
└─────────────┘         └──────────────────┘              │
                                 │                        │
                                 │    ┌──────────────────┐│
                                 └────│ ingredient_tags  ││
                                      ├──────────────────┤│
                                      │ ingredient_id    ├┘
                                      │ tag_id           │
                                      └──────────────────┘
```

---

## Usage Examples

### Basic Operations

```python
from database.db_connection import get_db_session
from database.ingredient_repository import IngredientRepository
from database.recipe_repository import RecipeRepository

# Get a database session
db = get_db_session()

# Create repositories
ingredient_repo = IngredientRepository(db)
recipe_repo = RecipeRepository(db)

# Create a recipe
recipe = recipe_repo.create(
    url="https://example.com/recipe",
    title="My Recipe"
)

# Create an ingredient
ingredient = ingredient_repo.create(
    name="salmon",
    amount=1.5,
    unit="lb",
    tag_names=["fish", "protein"],
    recipe_id=recipe.id
)

# Search ingredients
salmon_ingredients = ingredient_repo.search_by_name("salmon")
fish_ingredients = ingredient_repo.get_by_tag("fish")

# Close session when done
db.close()
```

### Integration with Existing Code

```python
from classes.Ingredient import Ingredient as IngredientClass
from database.db_connection import get_db_session
from database.ingredient_repository import IngredientRepository

# Your existing ingredient
ing = IngredientClass(name="salmon", amount=1.5, unit="lb")

# Save to database
db = get_db_session()
ingredient_repo = IngredientRepository(db)

db_ingredient = ingredient_repo.create(
    name=ing.get_name(),
    amount=ing.get_amount(),
    unit=ing.get_unit(),
    tag_names=[ing.get_tag()] if ing.get_tag() else []
)

db.close()
```

---

## Repository Methods

### IngredientRepository

- `create(name, amount, unit, tag_names, recipe_id)` - Create ingredient
- `get_by_id(ingredient_id)` - Get by ID
- `get_all(limit, offset)` - Get all (with pagination)
- `search_by_name(name)` - Search by name
- `get_by_tag(tag_name)` - Get all with specific tag
- `get_by_tags(tag_names, match_all)` - Get by multiple tags
- `get_by_recipe(recipe_id)` - Get all for a recipe
- `update(ingredient_id, ...)` - Update ingredient
- `delete(ingredient_id)` - Delete ingredient
- `bulk_create(ingredients_data)` - Create multiple at once
- `count()` - Get total count
- `count_by_tag(tag_name)` - Count by tag

### RecipeRepository

- `create(url, title, source_domain)` - Create recipe
- `get_by_id(recipe_id)` - Get by ID
- `get_by_url(url)` - Get by URL
- `get_or_create(url, title, source_domain)` - Get or create
- `get_all(limit, offset)` - Get all (with pagination)
- `search_by_title(title)` - Search by title
- `get_by_domain(domain)` - Get all from domain
- `update(recipe_id, ...)` - Update recipe
- `delete(recipe_id)` - Delete recipe (cascades to ingredients)
- `count()` - Get total count

### TagRepository

- `create(name, description)` - Create tag
- `get_by_id(tag_id)` - Get by ID
- `get_by_name(name)` - Get by name
- `get_or_create(name, description)` - Get or create
- `get_all()` - Get all tags
- `update(tag_id, ...)` - Update tag
- `delete(tag_id)` - Delete tag
- `search(query)` - Search tags
- `bulk_create(tag_names)` - Create multiple at once

---

## Troubleshooting

### Connection Issues

```python
from database.db_connection import test_connection
from database.db_config import DatabaseConfig

# Print configuration
DatabaseConfig.print_config()

# Test connection
test_connection()
```

### View SQL Queries

Edit `database/db_connection.py`:
```python
engine = create_engine(
    DATABASE_URL,
    echo=True,  # Set to True to see SQL queries
    ...
)
```

### Reset Database

```powershell
# Connect to PostgreSQL as the superuser
& 'C:\Program Files\PostgreSQL\15\bin\psql.exe' -U postgres -h localhost -p 5432
```
```sql
-- Drop and recreate (in the psql prompt)
DROP DATABASE auto_grocier;
CREATE DATABASE auto_grocier OWNER grocier_user;
\q
```
```powershell
# Re-run setup
python database\setup_database.py
```

---

## Migration Strategy

When schema changes are needed:

1. Make changes to `database/models.py`
2. Run migration:
   ```powershell
   python database\init_db.py
   ```
3. For production, consider using Alembic for proper migrations

---

## Performance Tips

1. **Use indexes** - Already created for commonly queried fields
2. **Batch operations** - Use `bulk_create()` for multiple inserts
3. **Connection pooling** - Already configured in `db_connection.py`
4. **Close sessions** - Always close database sessions when done

---

## Backup and Restore

### Backup
```powershell
& 'C:\Program Files\PostgreSQL\15\bin\pg_dump.exe' -U grocier_user -h localhost -p 5432 -d auto_grocier -F c -f backup.dump
```

### Restore
```powershell
& 'C:\Program Files\PostgreSQL\15\bin\pg_restore.exe' -U grocier_user -h localhost -p 5432 -d auto_grocier backup.dump
```

---

## Next Steps

1. ✅ Setup complete
2. ✅ Test database operations
3. 🔄 Integrate with `recipe_grabber.py` to save ingredients
4. 🔄 Modify `main.py` to use database storage
5. 🔄 Create analytics/reporting queries
6. 🔄 Build shopping list generator from stored ingredients

---

For questions or issues, refer to the DATABASE_PLAN.md file for architecture details.
