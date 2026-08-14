# UTILITY SCRIPT TO ADD MORE FOOD TYPES FROM WIKIPEDIA TABLES.
# WORKS FOR ANY NUMBER OF TABLES ON PAGE( as long as they are all the same structure ).
import re

import requests
from bs4 import BeautifulSoup


# Function to clean a string and remove everything except letters and spaces
def clean_string(input_string):
    # Use regular expressions to remove non-letter and non-space characters
    cleaned_string = re.sub(r'[^a-zA-Z\s]', '', input_string)
    return cleaned_string

# CHANGE THESE VARIABLES
# CHANGE THESE VARIABLES
file_name = "cheese_test.txt"
# URL of the Wikipedia page with the tables you want to scrape
url = 'https://en.wikipedia.org/wiki/List_of_cheeses'
identifier = 'Name'
# CHANGE THESE VARIABLES
# CHANGE THESE VARIABLES

# Send an HTTP GET request to the URL
response = requests.get(url)

# Check if the request was successful (status code 200)
if response.status_code == 200:
    # Parse the HTML content of the page using BeautifulSoup
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find all tables with the specified class or attributes
    tables = soup.find_all('table', {'class': 'wikitable'})  # Replace with the actual class or attributes of your target tables

    if tables:
        # Create an empty set to store unique pasta types
        unique_pasta_types = set()

        for table in tables:
            # Extract table data into a list of lists
            table_data = []
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all(['th', 'td'])
                cols = [col.text.strip() for col in cols]
                table_data.append(cols)

            # Check if the table has a "Type" column
            if identifier in table_data[0]:
                # Find the index of the "Type" column
                type_index = table_data[0].index(identifier)

                # Extract the "Type" column values from the table and skip the header row
                types_from_table = [row[type_index] for row in table_data[1:]]

                # Add the types from this table to the set of unique pasta types
                unique_pasta_types.update(types_from_table)

        # Convert the set of unique pasta types back to a list
        all_pasta_types = sorted(list(unique_pasta_types))

        # Save all pasta types to a text file
        with open('word_dictionaries/' + file_name, 'w') as file:
            for pasta_type in all_pasta_types:
                file.write(clean_string(pasta_type.lower()) + '\n')

        print("All unique pasta types saved to word_dictionaries/" + file_name)
    else:
        print("No tables with the specified class or attributes found on the page.")
else:
    print("Failed to retrieve the page. Status code:", response.status_code)


