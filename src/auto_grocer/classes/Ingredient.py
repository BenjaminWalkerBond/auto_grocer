from .IngredientList import IngredientList


class Ingredient(IngredientList):
    def __init__(self, name, amount=1, unit="none"):
        self.name = name
        self.amount = amount
        self.unit = unit
        self.tag = Ingredient.set_tag(self, self.name)
        # print(self.tag)
    def __str__(self):
        return f"{self.amount} {self.unit} {self.name} : {self.tag}"
    def set_tag(self, ingredientName):
        # print("get_tag Ingredient")
        return super().get_tag(ingredientName)
    def get_name(self):
        return self.name
    def get_tag(self):
        return self.tag
    def get_amount(self):
        return self.amount
    def get_unit(self):
        return self.unit

