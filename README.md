# Auto Grocier

An automated grocery shopping assistant that parses recipes and manages ingredients.

## 🔒 Security Notice

**NEVER commit `config.txt` to version control!** It contains sensitive credentials.

1. Copy `config.txt.example` to `config.txt`
2. Fill in your actual credentials in `config.txt`
3. The `.gitignore` file ensures `config.txt` stays local only

## Quick Start

1. **Activate virtual environment** (ALWAYS do this first!)
   ```bash
   source venv/bin/activate
   ```

2. **Configure your credentials** - Copy and edit the config file:
   ```bash
   cp config.txt.example config.txt
   # Then edit config.txt with your actual credentials
   ```
   
   Example `config.txt`:
   ```
   EMAIL=your-heb-email@example.com
   PASSWORD=your-heb-password
   CLAUDE_API_KEY=your-claude-api-key
   DATABASE_PASSWORD=your_secure_password
   ```

3. **Choose a mode and ingredient source** (edit `main.py`):
   
   **Mode:**
   - `MODE = 'test'` - Testing (safest, no checkout)
   - `MODE = 'checkout_with_prompt'` - Prompts before checkout
   - `MODE = 'auto_checkout'` - Fully automated (⚠️ careful!)
   
   **Ingredient Source:**
   - `USE_URLS = True` - Parse ingredients from recipe URLs
   - `USE_URLS = False` - Use hardcoded ingredient list

4. **Run the automation**
   ```bash
   python main.py
   ```

5. **Run database tests** (optional)
   ```bash
   python testing/test_connection.py
   python testing/test_database.py
   ```

## Documentation

All documentation is located in the `docs/` directory:

- **[Modes Guide](docs/MODES_GUIDE.md)** - Three operating modes: test, checkout_with_prompt, auto_checkout
- **[Ingredient Source Guide](docs/INGREDIENT_SOURCE_GUIDE.md)** - Recipe URLs vs. hardcoded ingredients
- **[Driver Logger Guide](docs/DRIVER_LOGGER_GUIDE.md)** - Debugging HEB website changes with HTML snapshots
- **[Claude Setup Guide](docs/CLAUDE_SETUP.md)** - API configuration and usage instructions
- **[PostgreSQL Installation](docs/POSTGRES_INSTALL.md)** - Database setup guide
- **[Database Plan](docs/DATABASE_PLAN.md)** - Database architecture and design
- **[Database Implementation](docs/DATABASE_IMPLEMENTATION.md)** - Implementation details
- **[Full Documentation](docs/README.md)** - Complete project documentation

## Project Structure

```
auto_grocier/
├── docs/                    # All documentation
├── classes/                 # Core ingredient classes
├── database/                # Database models and repositories
├── testing/                 # All test scripts
├── utility/                 # Utility scripts
├── word_dictionaries/       # Ingredient classification data
└── main.py                  # Main application entry point
```

## Important Notes

- **Always activate the virtual environment before running any commands!**
- **All test scripts are located in the `testing/` directory**
- Database credentials are stored in `config.txt` (not tracked in git)

## Configuration

Create a `config.txt` file in the root directory with:
```
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=auto_grocier
DATABASE_USER=grocier_user
DATABASE_PASSWORD=your_password
CLAUDE_API_KEY=your_api_key
```

See `docs/CLAUDE_SETUP.md` and `docs/POSTGRES_INSTALL.md` for detailed setup instructions.
