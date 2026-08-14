"""
Repository for Ingredient operations.
Provides CRUD operations for ingredients.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from .models import Ingredient, Tag
from .tag_repository import TagRepository


class IngredientRepository:
    """Repository for managing ingredients in the database"""

    def __init__(self, db: Session):
        self.db = db
        self.tag_repo = TagRepository(db)

    def create(self, name: str, amount: float, unit: str, tag_names: List[str] | None = None, recipe_id: int | None = None) -> Ingredient:
        """
        Create a new ingredient.

        Args:
            name: Ingredient name
            amount: Amount/quantity
            unit: Unit of measurement (e.g., 'cup', 'tablespoon', 'oz')
            tag_names: List of tag names to associate with this ingredient
            recipe_id: Optional recipe ID this ingredient belongs to

        Returns:
            Created Ingredient object
        """
        ingredient = Ingredient(
            name=name.lower(),
            amount=amount,
            unit=unit.lower(),
            recipe_id=recipe_id
        )

        # Add tags if provided
        if tag_names:
            for tag_name in tag_names:
                tag = self.tag_repo.get_or_create(tag_name)
                ingredient.tags.append(tag)

        self.db.add(ingredient)
        self.db.commit()
        self.db.refresh(ingredient)
        return ingredient

    def get_by_id(self, ingredient_id: int) -> Optional[Ingredient]:
        """Get an ingredient by its ID"""
        return self.db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()

    def get_all(self, limit: int | None = None, offset: int = 0) -> List[Ingredient]:
        """
        Get all ingredients with optional pagination.

        Args:
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns:
            List of Ingredient objects
        """
        query = self.db.query(Ingredient).order_by(Ingredient.created_at.desc())
        if limit:
            query = query.limit(limit).offset(offset)
        return query.all()

    def search_by_name(self, name: str) -> List[Ingredient]:
        """
        Search ingredients by name (case-insensitive partial match).

        Args:
            name: Search string

        Returns:
            List of matching ingredients
        """
        return self.db.query(Ingredient).filter(
            Ingredient.name.ilike(f'%{name.lower()}%')
        ).all()

    def get_by_tag(self, tag_name: str) -> List[Ingredient]:
        """
        Find all ingredients with a specific tag.

        Args:
            tag_name: Name of the tag

        Returns:
            List of ingredients with that tag
        """
        return self.db.query(Ingredient).join(
            Ingredient.tags
        ).filter(
            Tag.name == tag_name.lower()
        ).all()

    def get_by_tags(self, tag_names: List[str], match_all: bool = False) -> List[Ingredient]:
        """
        Find ingredients by multiple tags.

        Args:
            tag_names: List of tag names
            match_all: If True, ingredient must have all tags. If False, any tag matches.

        Returns:
            List of matching ingredients
        """
        if match_all:
            # Ingredient must have ALL tags
            query = self.db.query(Ingredient)
            for tag_name in tag_names:
                query = query.join(Ingredient.tags).filter(Tag.name == tag_name.lower())
            return query.all()
        else:
            # Ingredient can have ANY of the tags
            return self.db.query(Ingredient).join(
                Ingredient.tags
            ).filter(
                Tag.name.in_([name.lower() for name in tag_names])
            ).distinct().all()

    def get_by_recipe(self, recipe_id: int) -> List[Ingredient]:
        """
        Get all ingredients for a specific recipe.

        Args:
            recipe_id: Recipe ID

        Returns:
            List of ingredients
        """
        return self.db.query(Ingredient).filter(
            Ingredient.recipe_id == recipe_id
        ).all()

    def update(self, ingredient_id: int, name: str | None = None, amount: float | None = None,
               unit: str | None = None, tag_names: List[str] | None = None) -> Optional[Ingredient]:
        """
        Update an ingredient.

        Args:
            ingredient_id: ID of the ingredient to update
            name: New name (optional)
            amount: New amount (optional)
            unit: New unit (optional)
            tag_names: New list of tag names (optional, replaces existing tags)

        Returns:
            Updated Ingredient object or None if not found
        """
        ingredient = self.get_by_id(ingredient_id)
        if ingredient:
            if name is not None:
                ingredient.name = name.lower()
            if amount is not None:
                ingredient.amount = amount
            if unit is not None:
                ingredient.unit = unit.lower()
            if tag_names is not None:
                # Clear existing tags and add new ones
                ingredient.tags.clear()
                for tag_name in tag_names:
                    tag = self.tag_repo.get_or_create(tag_name)
                    ingredient.tags.append(tag)

            self.db.commit()
            self.db.refresh(ingredient)
        return ingredient

    def delete(self, ingredient_id: int) -> bool:
        """
        Delete an ingredient.

        Args:
            ingredient_id: ID of the ingredient to delete

        Returns:
            True if deleted, False if not found
        """
        ingredient = self.get_by_id(ingredient_id)
        if ingredient:
            self.db.delete(ingredient)
            self.db.commit()
            return True
        return False

    def bulk_create(self, ingredients_data: List[dict]) -> List[Ingredient]:
        """
        Create multiple ingredients at once.

        Args:
            ingredients_data: List of dictionaries with ingredient data
                             Each dict should have: name, amount, unit, and optionally tag_names, recipe_id

        Returns:
            List of created Ingredient objects
        """
        ingredients = []
        for data in ingredients_data:
            ingredient = self.create(
                name=data['name'],
                amount=data['amount'],
                unit=data['unit'],
                tag_names=data.get('tag_names', []),
                recipe_id=data.get('recipe_id')
            )
            ingredients.append(ingredient)
        return ingredients

    def count(self) -> int:
        """Get total count of ingredients"""
        return self.db.query(Ingredient).count()

    def count_by_tag(self, tag_name: str) -> int:
        """Count ingredients with a specific tag"""
        return self.db.query(Ingredient).join(
            Ingredient.tags
        ).filter(
            Tag.name == tag_name.lower()
        ).count()
