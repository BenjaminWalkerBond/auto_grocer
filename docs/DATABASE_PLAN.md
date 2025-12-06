# PostgreSQL Database Plan for Ingredient Storage

## Overview
This plan outlines the database schema and implementation strategy for storing ingredient objects in PostgreSQL.

## Current Ingredient Structure
```python
class Ingredient:
    - name: str
    - amount: float/int
    - unit: str
    - tag: str (single tag currently)
```

## Proposed Database Schema

### Option 1: Simple Schema with Array (Recommended for MVP)
```sql
CREATE TABLE ingredients (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    unit VARCHAR(50) NOT NULL,
    tags TEXT[] DEFAULT '{}',  -- PostgreSQL array for multiple tags
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for faster searches
CREATE INDEX idx_ingredient_name ON ingredients(name);
CREATE INDEX idx_ingredient_tags ON ingredients USING GIN(tags);  -- GIN index for array searches
```

**Pros:**
- Simple to implement
- Easy to query
- Good for small to medium datasets
- PostgreSQL arrays are efficient for this use case

**Cons:**
- Less normalized (but acceptable for this use case)
- Tags are duplicated across rows

---

### Option 2: Normalized Schema with Junction Table (Recommended for Production)
```sql
-- Main ingredients table
CREATE TABLE ingredients (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    unit VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, amount, unit)  -- Prevent exact duplicates
);

-- Tags lookup table
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Junction table for many-to-many relationship
CREATE TABLE ingredient_tags (
    ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (ingredient_id, tag_id)
);

-- Indexes for performance
CREATE INDEX idx_ingredient_name ON ingredients(name);
CREATE INDEX idx_tag_name ON tags(name);
CREATE INDEX idx_ingredient_tags_ingredient ON ingredient_tags(ingredient_id);
CREATE INDEX idx_ingredient_tags_tag ON ingredient_tags(tag_id);
```

**Pros:**
- Fully normalized
- Easy to manage tags (add/remove/rename)
- Better data integrity
- Efficient for complex queries
- Scalable for large datasets

**Cons:**
- More complex queries (requires JOINs)
- More tables to manage

---

### Option 3: Hybrid Schema with Recipe Context
```sql
-- Recipes table (for tracking where ingredients came from)
CREATE TABLE recipes (
    id SERIAL PRIMARY KEY,
    url VARCHAR(500) UNIQUE,
    title VARCHAR(500),
    source_domain VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ingredients table
CREATE TABLE ingredients (
    id SERIAL PRIMARY KEY,
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    unit VARCHAR(50) NOT NULL,
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_ingredient_recipe ON ingredients(recipe_id);
CREATE INDEX idx_ingredient_name ON ingredients(name);
CREATE INDEX idx_recipe_url ON recipes(url);
```

**Pros:**
- Maintains context of where ingredients came from
- Can track recipes over time
- Good for analytics (e.g., "which recipes use salmon?")
- Combines simplicity of arrays with relational structure

**Cons:**
- More complex than Option 1
- Requires managing recipe data

---

## Recommended Approach: **Option 2 (Normalized Schema)**

### Reasoning:
1. **Scalability**: Your ingredient tags come from predefined categories (cheese, fish, fruit, etc.)
2. **Data Integrity**: Tags are consistent and managed centrally
3. **Flexibility**: Easy to add new tags or modify existing ones
4. **Query Power**: Complex queries like "find all recipes with fish AND vegetables"
5. **Future-proof**: Can extend to include tag metadata (nutritional info, allergens, etc.)

---

## Implementation Plan

### Phase 1: Setup Database Connection
**Files to create:**
- `database/db_config.py` - Database connection configuration
- `database/db_connection.py` - Connection pool management
- `requirements.txt` - Add `psycopg2-binary` or `asyncpg`

### Phase 2: Create Database Models
**Files to create:**
- `database/models.py` - Database models and schema
- `database/migrations/001_create_tables.sql` - Initial schema
- `database/seed_data.sql` - Populate tags table with existing categories

### Phase 3: Create Database Operations
**Files to create:**
- `database/ingredient_repository.py` - CRUD operations for ingredients
- `database/tag_repository.py` - CRUD operations for tags

### Phase 4: Integration
**Files to modify:**
- `classes/Ingredient.py` - Add database save/load methods
- `classes/IngredientList.py` - Add bulk save/load methods
- `recipe_grabber.py` - Save ingredients after extraction

---

## Python Libraries Needed

### Option A: psycopg2 (Traditional)
```bash
pip install psycopg2-binary
```
- Mature and stable
- Synchronous
- Good documentation

### Option B: SQLAlchemy (ORM - Recommended)
```bash
pip install sqlalchemy psycopg2-binary
```
- Object-Relational Mapping
- Database agnostic
- Migration support with Alembic
- Type safety

### Option C: asyncpg (High Performance)
```bash
pip install asyncpg
```
- Asynchronous
- Fastest PostgreSQL driver
- Requires async/await pattern

**Recommendation: SQLAlchemy + psycopg2** for ease of use and maintainability.

---

## Sample Code Structure

### Database Connection
```python
# database/db_connection.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv(
    'DATABASE_URL', 
    'postgresql://user:password@localhost:5432/auto_grocier'
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### Models
```python
# database/models.py
from sqlalchemy import Column, Integer, String, DECIMAL, TIMESTAMP, Table, ForeignKey
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

# Junction table
ingredient_tags = Table(
    'ingredient_tags',
    Base.metadata,
    Column('ingredient_id', Integer, ForeignKey('ingredients.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

class Ingredient(Base):
    __tablename__ = 'ingredients'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    amount = Column(DECIMAL(10, 2), nullable=False)
    unit = Column(String(50), nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    tags = relationship('Tag', secondary=ingredient_tags, back_populates='ingredients')

class Tag(Base):
    __tablename__ = 'tags'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Relationship
    ingredients = relationship('Ingredient', secondary=ingredient_tags, back_populates='tags')
```

### Repository Pattern
```python
# database/ingredient_repository.py
from database.models import Ingredient, Tag
from sqlalchemy.orm import Session

class IngredientRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, name: str, amount: float, unit: str, tag_names: list):
        """Create a new ingredient with tags"""
        ingredient = Ingredient(name=name, amount=amount, unit=unit)
        
        # Get or create tags
        for tag_name in tag_names:
            tag = self.db.query(Tag).filter(Tag.name == tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                self.db.add(tag)
            ingredient.tags.append(tag)
        
        self.db.add(ingredient)
        self.db.commit()
        self.db.refresh(ingredient)
        return ingredient
    
    def get_by_id(self, ingredient_id: int):
        """Get ingredient by ID"""
        return self.db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    
    def get_all(self):
        """Get all ingredients"""
        return self.db.query(Ingredient).all()
    
    def search_by_name(self, name: str):
        """Search ingredients by name"""
        return self.db.query(Ingredient).filter(Ingredient.name.ilike(f'%{name}%')).all()
    
    def search_by_tag(self, tag_name: str):
        """Find all ingredients with a specific tag"""
        return self.db.query(Ingredient).join(Ingredient.tags).filter(Tag.name == tag_name).all()
    
    def delete(self, ingredient_id: int):
        """Delete an ingredient"""
        ingredient = self.get_by_id(ingredient_id)
        if ingredient:
            self.db.delete(ingredient)
            self.db.commit()
            return True
        return False
```

---

## Configuration Updates

### Add to config.txt
```
# Database Configuration
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=auto_grocier
DATABASE_USER=postgres
DATABASE_PASSWORD=your_password
```

### Update requirements.txt
```
# Add these lines
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
alembic>=1.12.0  # For database migrations
```

---

## Migration Strategy

### Step 1: Install PostgreSQL
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install postgresql postgresql-contrib

# Create database
sudo -u postgres psql
CREATE DATABASE auto_grocier;
CREATE USER grocier_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE auto_grocier TO grocier_user;
```

### Step 2: Create Initial Schema
```bash
# Run migration script
python database/migrations/run_migrations.py
```

### Step 3: Seed Tag Data
```bash
# Populate tags from existing word_dictionaries
python database/seed_tags.py
```

---

## Testing Strategy

1. **Unit Tests**: Test repository methods
2. **Integration Tests**: Test with actual database
3. **Migration Tests**: Ensure schema changes work
4. **Performance Tests**: Query optimization

---

## Future Enhancements

1. **Recipe Storage**: Store entire recipes with ingredient lists
2. **Shopping Lists**: Generate optimized shopping lists
3. **Nutritional Data**: Add nutritional information to ingredients
4. **User Preferences**: Track user's favorite ingredients/recipes
5. **Price Tracking**: Store ingredient prices over time
6. **Inventory Management**: Track what's in your pantry
7. **Analytics**: Recipe trends, most used ingredients, cost analysis

---

## Estimated Timeline

- **Phase 1 (Setup)**: 2-3 hours
- **Phase 2 (Models)**: 2-3 hours
- **Phase 3 (Operations)**: 4-5 hours
- **Phase 4 (Integration)**: 3-4 hours
- **Testing**: 2-3 hours

**Total**: ~15-20 hours

---

## Next Steps

1. Install PostgreSQL locally or use cloud service (AWS RDS, Heroku Postgres, etc.)
2. Create database and user
3. Add database credentials to config.txt
4. Install Python dependencies
5. Create database folder structure
6. Implement models and migrations
7. Create repository classes
8. Integrate with existing code
9. Write tests
10. Deploy

Would you like me to proceed with implementing any of these phases?
