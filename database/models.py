"""
Database models for the auto_grocier application.
Defines the schema for ingredients, tags, and recipes.
"""
from sqlalchemy import Column, Integer, String, DECIMAL, TIMESTAMP, Table, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

# Junction table for many-to-many relationship between ingredients and tags
ingredient_tags = Table(
    'ingredient_tags',
    Base.metadata,
    Column('ingredient_id', Integer, ForeignKey('ingredients.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)
)


class Tag(Base):
    """
    Tag model for categorizing ingredients.
    Examples: 'cheese', 'fish', 'fruit', 'vegetable', 'meat', etc.
    """
    __tablename__ = 'tags'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    
    # Relationship: A tag can be associated with many ingredients
    ingredients = relationship('Ingredient', secondary=ingredient_tags, back_populates='tags')
    
    def __repr__(self):
        return f"<Tag(id={self.id}, name='{self.name}')>"
    
    def to_dict(self):
        """Convert tag to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Recipe(Base):
    """
    Recipe model for tracking where ingredients came from.
    Stores recipe URL and metadata.
    """
    __tablename__ = 'recipes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(500), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    source_domain = Column(String(255), nullable=True, index=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship: A recipe has many ingredients
    ingredients = relationship('Ingredient', back_populates='recipe', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Recipe(id={self.id}, title='{self.title}', url='{self.url}')>"
    
    def to_dict(self):
        """Convert recipe to dictionary"""
        return {
            'id': self.id,
            'url': self.url,
            'title': self.title,
            'description': self.description,
            'source_domain': self.source_domain,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'ingredient_count': len(self.ingredients) if self.ingredients else 0
        }


class Ingredient(Base):
    """
    Ingredient model for storing recipe ingredients.
    Includes amount, unit, name, and associated tags.
    """
    __tablename__ = 'ingredients'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    recipe_id = Column(Integer, ForeignKey('recipes.id', ondelete='CASCADE'), nullable=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    amount = Column(DECIMAL(10, 3), nullable=False)  # Support decimals like 0.25, 1.5, etc.
    unit = Column(String(50), nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    recipe = relationship('Recipe', back_populates='ingredients')
    tags = relationship('Tag', secondary=ingredient_tags, back_populates='ingredients')
    
    def __repr__(self):
        tag_names = [tag.name for tag in self.tags] if self.tags else []
        return f"<Ingredient(id={self.id}, name='{self.name}', amount={self.amount}, unit='{self.unit}', tags={tag_names})>"
    
    def __str__(self):
        """String representation matching the original Ingredient class format"""
        tag_names = [tag.name for tag in self.tags] if self.tags else ['none']
        tag_str = ', '.join(tag_names)
        return f"{self.amount} {self.unit} {self.name} : {tag_str}"
    
    def to_dict(self):
        """Convert ingredient to dictionary"""
        return {
            'id': self.id,
            'recipe_id': self.recipe_id,
            'name': self.name,
            'amount': float(self.amount),
            'unit': self.unit,
            'tags': [tag.name for tag in self.tags] if self.tags else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
