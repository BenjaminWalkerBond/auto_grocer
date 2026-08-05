import os


def read_file(file_path):
    with open(file_path, 'r') as file:
        lines = set(file.read().splitlines())
    return lines

def combine_and_write_files(output_file, *unique_to_files):
    combined_strings = set()

    for unique_to_file in unique_to_files:
        combined_strings.update(unique_to_file)

    combined_strings = sorted(combined_strings)

    with open(output_file, 'w') as file:
        for string in combined_strings:
            file.write(string + '\n')

def main():
    file1_rel_path = "./pre_process/cheese_test.txt"
    file2_rel_path = "./pre_process/cheese_old.txt"

    output_file = "./word_dictionaries/cheese.txt"

    # Convert relative paths to absolute paths
    file1_abs_path = os.path.abspath(file1_rel_path)
    file2_abs_path = os.path.abspath(file2_rel_path)

    file1_lines = read_file(file1_abs_path)
    file2_lines = read_file(file2_abs_path)

    unique_to_file1 = file1_lines - file2_lines
    unique_to_file2 = file2_lines - file1_lines

    print("Strings unique to", file1_abs_path, ":")
    for string in unique_to_file1:
        print(string)

    print("\nStrings unique to", file2_abs_path, ":")
    for string in unique_to_file2:
        print(string)

    combine_and_write_files(output_file, unique_to_file1, unique_to_file2)
    print(f"Combined unique strings written to '{output_file}'.")

if __name__ == "__main__":
    main()

