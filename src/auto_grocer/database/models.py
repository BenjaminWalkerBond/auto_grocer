"""
Database models for the auto_grocer application.
Defines the schema for ingredients, tags, and recipes.
"""
from datetime import datetime

from sqlalchemy import DECIMAL, TIMESTAMP, Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, nullable=False)

    # Relationship: A tag can be associated with many ingredients
    ingredients: Mapped[list['Ingredient']] = relationship(
        'Ingredient', secondary=ingredient_tags, back_populates='tags'
    )

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    cook_time: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Cook time in minutes
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationship: A recipe has many ingredients
    ingredients: Mapped[list['Ingredient']] = relationship(
        'Ingredient', back_populates='recipe', cascade='all, delete-orphan'
    )

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
            'cook_time': self.cook_time,
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('recipes.id', ondelete='CASCADE'), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # DECIMAL column; treated as float throughout the app layer.
    amount: Mapped[float] = mapped_column(DECIMAL(10, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    recipe: Mapped['Recipe | None'] = relationship('Recipe', back_populates='ingredients')
    tags: Mapped[list['Tag']] = relationship(
        'Tag', secondary=ingredient_tags, back_populates='ingredients'
    )

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
