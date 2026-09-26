"""
Repository for Tag operations.
Provides CRUD operations for tags.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from .models import Tag


class TagRepository:
    """Repository for managing tags in the database"""

    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str, description: str | None = None) -> Tag:
        """
        Create a new tag.

        Args:
            name: Tag name (e.g., 'cheese', 'fish', 'vegetable')
            description: Optional description

        Returns:
            Created Tag object
        """
        tag = Tag(name=name.lower(), description=description)
        self.db.add(tag)
        self.db.commit()
        self.db.refresh(tag)
        return tag

    def get_by_id(self, tag_id: int) -> Optional[Tag]:
        """Get a tag by its ID"""
        return self.db.query(Tag).filter(Tag.id == tag_id).first()

    def get_by_name(self, name: str) -> Optional[Tag]:
        """Get a tag by its name"""
        return self.db.query(Tag).filter(Tag.name == name.lower()).first()

    def get_or_create(self, name: str, description: str | None = None) -> Tag:
        """
        Get an existing tag or create a new one if it doesn't exist.

        Args:
            name: Tag name
            description: Optional description (only used if creating)

        Returns:
            Tag object
        """
        tag = self.get_by_name(name)
        if not tag:
            tag = self.create(name, description)
        return tag

    def get_all(self) -> List[Tag]:
        """Get all tags"""
        return self.db.query(Tag).order_by(Tag.name).all()

    def update(self, tag_id: int, name: str | None = None, description: str | None = None) -> Optional[Tag]:
        """
        Update a tag.

        Args:
            tag_id: ID of the tag to update
            name: New name (optional)
            description: New description (optional)

        Returns:
            Updated Tag object or None if not found
        """
        tag = self.get_by_id(tag_id)
        if tag:
            if name is not None:
                tag.name = name.lower()
            if description is not None:
                tag.description = description
            self.db.commit()
            self.db.refresh(tag)
        return tag

    def delete(self, tag_id: int) -> bool:
        """
        Delete a tag.

        Args:
            tag_id: ID of the tag to delete

        Returns:
            True if deleted, False if not found
        """
        tag = self.get_by_id(tag_id)
        if tag:
            self.db.delete(tag)
            self.db.commit()
            return True
        return False

    def search(self, query: str) -> List[Tag]:
        """
        Search tags by name.

        Args:
            query: Search string

        Returns:
            List of matching tags
        """
        return self.db.query(Tag).filter(Tag.name.ilike(f'%{query.lower()}%')).all()

    def bulk_create(self, tag_names: List[str]) -> List[Tag]:
        """
        Create multiple tags at once (get or create).

        Args:
            tag_names: List of tag names

        Returns:
            List of Tag objects
        """
        tags = []
        for name in tag_names:
            tag = self.get_or_create(name)
            tags.append(tag)
        return tags
