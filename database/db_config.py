"""
Database configuration module.
Loads database connection parameters from config.txt or environment variables.
"""
import os


def parse_config(config_path):
    """
    Parse the config.txt file and return a dictionary of key-value pairs.
    Supports KEY=VALUE format and ignores comments (lines starting with #).
    """
    config_dict = {}
    
    if not os.path.exists(config_path):
        return config_dict
    
    with open(config_path, 'r') as file:
        for line in file:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Parse KEY=VALUE format
            if '=' in line:
                key, value = line.split('=', 1)  # Split only on first =
                config_dict[key.strip()] = value.strip()
    
    return config_dict


# Find the absolute path of config.txt
config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.txt')
config = parse_config(config_path)


class DatabaseConfig:
    """Database configuration class"""
    
    # Get database settings from config or environment variables
    DB_HOST = config.get('DATABASE_HOST') or os.environ.get('DATABASE_HOST', 'localhost')
    DB_PORT = config.get('DATABASE_PORT') or os.environ.get('DATABASE_PORT', '5432')
    DB_NAME = config.get('DATABASE_NAME') or os.environ.get('DATABASE_NAME', 'auto_grocier')
    DB_USER = config.get('DATABASE_USER') or os.environ.get('DATABASE_USER', 'postgres')
    DB_PASSWORD = config.get('DATABASE_PASSWORD') or os.environ.get('DATABASE_PASSWORD', '')
    
    @classmethod
    def get_database_url(cls):
        """Construct the database URL for SQLAlchemy.

        A ``DATABASE_URL`` environment variable, when set, takes top priority and
        is returned verbatim. This lets the Dockerized MCP server point at the
        Postgres *service* on the compose network (host ``postgres``) without
        editing config.txt, which otherwise hard-codes ``localhost``.
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
