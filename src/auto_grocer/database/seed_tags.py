"""
Seed the database with predefined tags from word_dictionaries folder.
"""
import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_grocer.database.db_connection import get_db_session
from auto_grocer.database.tag_repository import TagRepository


def seed_tags():
    """Seed the database with tags from word_dictionaries"""
    try:
        print("=" * 60)
        print("Seeding Tags from word_dictionaries")
        print("=" * 60)
        print()

        # Get database session
        db = get_db_session()
        tag_repo = TagRepository(db)

        # Define predefined tags (from IngredientList.tags)
        predefined_tags = [
            ("cheese", "Cheese and dairy products"),
            ("fat", "Solid fats such as butter, ghee, margarine, and lard"),
            ("fish", "Fish and seafood"),
            ("fruit", "Fruits"),
            ("meat", "Meat products"),
            ("oil", "Liquid cooking oils"),
            ("pasta", "Pasta and noodles"),
            ("spice", "Spices and seasonings"),
            ("tree_nut", "Tree nuts"),
            ("vegetable", "Vegetables"),
            ("wine", "Wine and alcoholic beverages"),
            ("eggs", "Eggs"),
            ("milk", "Milk products"),
            ("none", "Uncategorized ingredients")
        ]

        created_count = 0
        existing_count = 0

        for tag_name, description in predefined_tags:
            existing_tag = tag_repo.get_by_name(tag_name)
            if existing_tag:
                print(f"  ↻ Tag '{tag_name}' already exists")
                existing_count += 1
            else:
                tag_repo.create(tag_name, description)
                print(f"  ✓ Created tag '{tag_name}'")
                created_count += 1

        db.close()

        print()
        print("Summary:")
        print(f"  - Tags created: {created_count}")
        print(f"  - Tags already existed: {existing_count}")
        print(f"  - Total tags: {created_count + existing_count}")
        print()
        print("=" * 60)
        print("Tag seeding complete!")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"✗ Error seeding tags: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = seed_tags()
    sys.exit(0 if success else 1)
