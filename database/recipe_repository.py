"""
Repository for Recipe operations.
Provides CRUD operations for recipes.
"""
from sqlalchemy.orm import Session
from .models import Recipe
from typing import List, Optional
from urllib.parse import urlparse


class RecipeRepository:
    """Repository for managing recipes in the database"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, url: str, title: str = None, source_domain: str = None, description: str = None, cook_time: int = None) -> Recipe:
        """
        Create a new recipe.
        
        Args:
            url: Recipe URL
            title: Recipe title (optional)
            source_domain: Source domain (optional, will be extracted from URL if not provided)
            description: Recipe description used for natural-language matching (optional)
            cook_time: Cook time in minutes (optional)
            
        Returns:
            Created Recipe object
        """
        # Extract domain from URL if not provided
        if not source_domain:
            parsed_url = urlparse(url)
            source_domain = parsed_url.netloc
        
        recipe = Recipe(
            url=url,
            title=title,
            description=description,
            source_domain=source_domain,
            cook_time=cook_time
        )
        self.db.add(recipe)
        self.db.commit()
        self.db.refresh(recipe)
        return recipe
    
    def get_by_id(self, recipe_id: int) -> Optional[Recipe]:
        """Get a recipe by its ID"""
        return self.db.query(Recipe).filter(Recipe.id == recipe_id).first()
    
    def get_by_url(self, url: str) -> Optional[Recipe]:
        """Get a recipe by its URL"""
        return self.db.query(Recipe).filter(Recipe.url == url).first()
    
    def get_or_create(self, url: str, title: str = None, source_domain: str = None, description: str = None, cook_time: int = None) -> Recipe:
        """
        Get an existing recipe or create a new one if it doesn't exist.
        
        Args:
            url: Recipe URL
            title: Recipe title (optional)
            source_domain: Source domain (optional)
            description: Recipe description (optional)
            cook_time: Cook time in minutes (optional)
            
        Returns:
            Recipe object
        """
        recipe = self.get_by_url(url)
        if not recipe:
            recipe = self.create(url, title, source_domain, description, cook_time)
        return recipe
    
    def get_all(self, limit: int = None, offset: int = 0) -> List[Recipe]:
        """
        Get all recipes with optional pagination.
        
        Args:
            limit: Maximum number of results to return
            offset: Number of results to skip
            
        Returns:
            List of Recipe objects
        """
        query = self.db.query(Recipe).order_by(Recipe.created_at.desc())
        if limit:
            query = query.limit(limit).offset(offset)
        return query.all()
    
    def search_by_title(self, title: str) -> List[Recipe]:
        """
        Search recipes by title (case-insensitive partial match).
        
        Args:
            title: Search string
            
        Returns:
            List of matching recipes
        """
        return self.db.query(Recipe).filter(
            Recipe.title.ilike(f'%{title}%')
        ).all()
    
    def search_recipes(self, query: str) -> List[Recipe]:
        """
        Search recipes by title OR description (case-insensitive partial match).
        
        Args:
            query: Search string
            
        Returns:
            List of matching recipes
        """
        pattern = f'%{query}%'
        return self.db.query(Recipe).filter(
            Recipe.title.ilike(pattern) | Recipe.description.ilike(pattern)
        ).all()
    
    def get_by_domain(self, domain: str) -> List[Recipe]:
        """
        Get all recipes from a specific domain.
        
        Args:
            domain: Source domain (e.g., 'cookingclassy.com')
            
        Returns:
            List of recipes from that domain
        """
        return self.db.query(Recipe).filter(
            Recipe.source_domain.ilike(f'%{domain}%')
        ).all()
    
    def update(self, recipe_id: int, url: str = None, title: str = None, source_domain: str = None, description: str = None, cook_time: int = None) -> Optional[Recipe]:
        """
        Update a recipe.
        
        Args:
            recipe_id: ID of the recipe to update
            url: New URL (optional)
            title: New title (optional)
            source_domain: New source domain (optional)
            description: New description (optional)
            cook_time: New cook time in minutes (optional)
            
        Returns:
            Updated Recipe object or None if not found
        """
        recipe = self.get_by_id(recipe_id)
        if recipe:
            if url is not None:
                recipe.url = url
            if title is not None:
                recipe.title = title
            if source_domain is not None:
                recipe.source_domain = source_domain
            if description is not None:
                recipe.description = description
            if cook_time is not None:
                recipe.cook_time = cook_time
            self.db.commit()
            self.db.refresh(recipe)
        return recipe
    
    def delete(self, recipe_id: int) -> bool:
        """
        Delete a recipe (and all associated ingredients due to cascade).
        
        Args:
            recipe_id: ID of the recipe to delete
            
        Returns:
            True if deleted, False if not found
        """
        recipe = self.get_by_id(recipe_id)
        if recipe:
            self.db.delete(recipe)
            self.db.commit()
            return True
        return False
    
    def count(self) -> int:
        """Get total count of recipes"""
        return self.db.query(Recipe).count()
    
    def count_by_domain(self, domain: str) -> int:
        """Count recipes from a specific domain"""
        return self.db.query(Recipe).filter(
            Recipe.source_domain.ilike(f'%{domain}%')
        ).count()
