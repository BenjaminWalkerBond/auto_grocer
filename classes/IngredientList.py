import os


class IngredientList:

    tags_dict: dict[str, str] = {}
    tags= ["cheese","fish","fruit","meat","oil","pasta","spice","tree_nut","vegetable","wine"]
    tags_constant = {"eggs","milk","none"}

    def init_dicts(self):
        # load all txt files in the word_dictionaries folder into tags_dict
        # get the parent directory of the current file
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        for path in os.scandir(os.path.join(parent_dir, "word_dictionaries")):
            # print(path)
            if path.is_file() and path.name.endswith(".txt"):
                tag = os.path.splitext(path.name)[0]
                print("Creating tags from dictionary from: " + path.name)
                with open(path.path) as f:
                    for line in f:
                        # print("line is: "+line.strip()+"\n")
                        self.tags_dict[line.strip()] = tag

        #  initialize each dictionary with their respective word files
        print("Initialized all tag dictionaries \n")

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
    def _lookup(self, key, allow_spice=True):
        """Look up one word/phrase, suppressing 'spice' for fresh ingredients."""
        tag = self.tags_dict.get(key)
        if tag == "spice" and not allow_spice:
            return None
        return tag

    def get_tag(self,ingredientName):
        ingredientName = ingredientName.lower()
        # "fresh <herb>" is produce, not a pantry spice (e.g. "fresh cilantro"
        # is bought by the bunch), so never resolve a fresh item to "spice".
        allow_spice = "fresh" not in ingredientName.split(" ")
        tag=self._lookup(ingredientName, allow_spice)
        # check if self.tags.get(ingredientName) is not in the dictionary
        if tag is None:
            ingredientName = ingredientName.split(" ")
            # check each word in the ingredient name for a tag match
            for word in ingredientName:
                check_word = self._lookup(word, allow_spice)
                if check_word is not None:
                    tag = check_word
                    break
            i = 0
            while i < len(ingredientName)-1:
                compound_word = ingredientName[i] + " " + ingredientName[i+1]
                compound_tag = self._lookup(compound_word, allow_spice)
                if compound_tag is not None:
                    tag = compound_tag
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

