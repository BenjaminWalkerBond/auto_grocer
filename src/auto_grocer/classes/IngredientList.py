import logging
import os

logger = logging.getLogger(__name__)


class IngredientList:

    tags_dict: dict[str, str] = {}
    tags= ["cheese","fat","fish","fruit","meat","oil","pasta","spice","tree_nut","vegetable","wine"]
    tags_constant = {"eggs","milk","none"}

    def init_dicts(self):
        # load all txt files in the word_dictionaries folder into tags_dict
        # get the parent directory of the current file
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        loaded = 0
        for path in os.scandir(os.path.join(parent_dir, "word_dictionaries")):
            if path.is_file() and path.name.endswith(".txt"):
                tag = os.path.splitext(path.name)[0]
                # Debug, not info: an IngredientList is built on every
                # add_groceries call, so this used to print a dozen lines into
                # the MCP client log per request.
                logger.debug("Loading tag dictionary", extra={"dictionary": path.name})
                with open(path.path) as f:
                    for line in f:
                        self.tags_dict[line.strip()] = tag
                loaded += 1

        logger.debug("Initialized tag dictionaries", extra={"count": loaded})

        self.tags_dict["eggs"] = "eggs"
        self.tags_dict["milk"] = "milk"
    def __init__(self):
        self.init_dicts()
        self.ingredients = []
    def add_ingredient(self, ingredient):
        self.ingredients.append(ingredient)
    def remove_last_ingredient(self):
        return self.ingredients.pop()

    # need to alter algorithim to search for compound words like "green beans"
    def get_tag(self,ingredientName):
        ingredientName = ingredientName.lower()
        tag=self.tags_dict.get(ingredientName)
        # check if self.tags.get(ingredientName) is not in the dictionary
        if tag is None:
            ingredientName = ingredientName.split(" ")
            # check each word in the ingredient name for a tag match
            for word in ingredientName:
                check_word = self.tags_dict.get(word)
                if check_word is not None:
                    tag = self.tags_dict.get(word)
                    break
            i = 0
            while i < len(ingredientName)-1:
                compound_word = ingredientName[i] + " " + ingredientName[i+1]
                if self.tags_dict.get(compound_word) is not None:
                    tag = self.tags_dict.get(compound_word)
                    break
                i += 1
        else:
            print()
        # print("get_tag IngredientList")
        # print("ingredientName: ", ingredientName)
        return tag
    def get_ingredients(self):
        return self.ingredients
    def show_list(self):
        print("INGREDIENT LIST: \n")
        for ingredient in self.ingredients:
            print(ingredient)

