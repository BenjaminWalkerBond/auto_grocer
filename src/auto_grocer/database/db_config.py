"""
Database configuration module.
Loads database connection parameters from the environment (.env file).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the project's .env (repo root) so DATABASE_* settings are available even
# when this module is imported without an entry point having loaded it first.
# Real environment variables (e.g. DATABASE_URL from Docker Compose) take
# precedence — load_dotenv does not override existing vars.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class DatabaseConfig:
    """Database configuration class"""

    # Database settings from the environment (.env or real env vars).
    DB_HOST = os.environ.get('DATABASE_HOST', 'localhost')
    DB_PORT = os.environ.get('DATABASE_PORT', '5432')
    DB_NAME = os.environ.get('DATABASE_NAME', 'auto_grocer')
    DB_USER = os.environ.get('DATABASE_USER', 'postgres')
    DB_PASSWORD = os.environ.get('DATABASE_PASSWORD', '')

    @classmethod
    def get_database_url(cls):
        """Construct the database URL for SQLAlchemy.

        A ``DATABASE_URL`` environment variable, when set, takes top priority and
        is returned verbatim. This lets the Dockerized MCP server point at the
        Postgres *service* on the compose network (host ``postgres``) without
        editing .env, whose DATABASE_HOST defaults to ``localhost``.
        """
        override = os.environ.get('DATABASE_URL')
        if override:
            return override
        return f"postgresql://{cls.DB_USER}:{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"

    @classmethod
    def print_config(cls):
        """Print current database configuration (without password)"""
        print("Database Configuration:")
        print(f"  Host: {cls.DB_HOST}")
        print(f"  Port: {cls.DB_PORT}")
        print(f"  Database: {cls.DB_NAME}")
        print(f"  User: {cls.DB_USER}")
        print(f"  Password: {'*' * len(cls.DB_PASSWORD) if cls.DB_PASSWORD else 'Not set'}")


# Export the configuration
db_config = DatabaseConfig()
