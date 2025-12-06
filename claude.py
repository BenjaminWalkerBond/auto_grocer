import os
import anthropic


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


# Find the absolute path of the file called config.txt in the current directory
file_path = os.path.join(os.path.dirname(__file__), 'config.txt')

# Parse the config file
config = parse_config(file_path)

# Get Claude API key from config or environment variable
claude_api_key = config.get('CLAUDE_API_KEY') or os.environ.get("ANTHROPIC_API_KEY")

if not claude_api_key:
    print("ERROR: No Claude API key found.")
    print("Please add CLAUDE_API_KEY=your-key-here to config.txt")
    print("or set the ANTHROPIC_API_KEY environment variable")
    print("See CLAUDE_SETUP.md for instructions.")
else:
    print(f"✓ Claude API key loaded successfully: {claude_api_key[:20]}...")

# Initialize the Anthropic client
client = anthropic.Anthropic(api_key=claude_api_key) if claude_api_key else None


def get_ingredients_gpt(url_list):  # Not currently working
    """
    Extract ingredients from URLs using Claude Sonnet.
    Note: This function doesn't actually fetch the URL content - it expects the caller to do that.
    """
    if client is None:
        raise Exception("Claude API client not initialized. Please add your Claude API key to config.txt (line 5) or set the ANTHROPIC_API_KEY environment variable. See CLAUDE_SETUP.md for instructions.")
    
    ingredient_list = []

    for url in url_list:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": f"Please grab the ingredients from this url and return them in a comma seperated list: {url}\n"
                }
            ]
        )
        
        print("claude response: " + message.content[0].text)
        
        verified = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": f"Please verify that the following text separates each distinct ingredient by a comma: {message.content[0].text}\n. If it does not, please insert commas where appropriate and return the list of comma separated ingredients. Do not include any other text."
                }
            ]
        )

        ingredient_list.append(verified.content[0].text)
    
    return ingredient_list


def get_ingredients_gpt_txt(txt):
    """
    Extract ingredients from text using Claude Sonnet.
    
    Args:
        txt: The text content from a recipe webpage
        
    Returns:
        A list containing comma-separated ingredients with their measurements
    """
    if client is None:
        raise Exception("Claude API client not initialized. Please add your Claude API key to config.txt (line 5) or set the ANTHROPIC_API_KEY environment variable. See CLAUDE_SETUP.md for instructions.")
    
    ingredient_list = []

    # get the amount of characters in the text
    char_count = len(txt)
    
    # Truncate text if too long (Claude has context limits)
    # Claude Sonnet supports up to 200k tokens, but we'll be conservative
    max_chars = 100000
    if char_count > max_chars:
        txt = txt[:max_chars]
        print(f"Warning: Text truncated from {char_count} to {max_chars} characters")

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"Please grab the ingredients and their measurements from the following text and return them in a comma seperated list in this format: AMOUNT UNIT: INGREDIENT. Make sure to only grab the ingredients from the ingredient section, and do not count ingredients twice. {txt}\n"
            }
        ]
    )

    verified = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"Please verify that the following text separates each distinct ingredient by a comma, and that the format of AMOUNT UNIT: INGREDIENT, AMOUNT UNIT: INGREDIENT , etc. was followed: {message.content[0].text}\n. If it does not, please insert commas where appropriate and return ONLY the list of comma separated ingredients. DO NOT include any other text."
            }
        ]
    )

    ingredient_list.append(verified.content[0].text)
    return ingredient_list


def get_recipe_gpt_txt(txt):
    """
    Placeholder function for future recipe extraction.
    """
    return 0


# url_list = [
#     "https://www.cookingclassy.com/skillet-seared-salmon-with-garlic-lemon-butter-sauce/",
# ]

# test the function
# print(get_ingredients_gpt(url_list))