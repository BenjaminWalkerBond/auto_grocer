import os
import openai

# find the absolute path of the file called config.txt in the current directory
file_path = os.path.join(os.path.dirname(__file__), 'config.txt')
# open the file in read mode
file = open(file_path, "r")
# split the file into a list of strings


openai_config = file.read().split("\n")
openai.organization = openai_config[2]
openai.api_key = openai_config[3]
# filter the json object by the json attribute "id" and print it
list = openai.Model.list()
list.data.sort(key=lambda x: x.id)
# for model in list.data:
#     print(model.id)



def get_ingredients_gpt(url_list): # Not currently working

    ingredient_list = []

    for url in url_list:

        completion = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": "Please grab the ingredients from this url and return them in a comma seperated list: " + url + " \n"}
            ]
        )
        print("chat gpt response: " + completion.choices[0].message.content)
        verified = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": "Please verify that the following text separates each distinct ingredient by a comma: " + completion.choices[0].message.content + " \n. If it does not, please insert commas where appropriate and return the list of comma separated ingredients. Do not include any other text."}
            ],
            # frequency_penalty=2.0,
        )  

        ingredient_list.append(verified.choices[0].message.content)
    return ingredient_list

def get_ingredients_gpt_txt(txt):

    ingredient_list = []

    # get the amount of character in the text
    char_count = len(txt)

    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-16k",
        messages=[
            {"role": "user", "content": "Please grab the ingredients and their measurements from the following text and return them in a comma seperated list in this format: AMOUNT UNIT: INGREDIENT. Make sure to only grab the ingredients from the ingredient section, and do not count ingredients twice. " + txt + " \n"}
        ]
    )

    verified = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-16k",
        messages=[
            {"role": "user", "content": "Please verify that the following text separates each distinct ingredient by a comma, and that the format of AMOUNT UNIT: INGREDIENT, AMOUNT UNIT: INGREDIENT , etc. was followed: " + completion.choices[0].message.content + " \n. If it does not, please insert commas where appropriate and return ONLY the list of comma separated ingredients. DO NOT include any other text."}
        ],
        # frequency_penalty=2.0,
    )  

    ingredient_list.append(verified.choices[0].message.content)
    return ingredient_list

def get_recipe_gpt_txt(txt):
    return 0
# url_list = [
#     "https://www.cookingclassy.com/skillet-seared-salmon-with-garlic-lemon-butter-sauce/",
# ]

# test the function
# print(get_ingredients_gpt(url_list))