import hashlib
import json
import logging
import os
import shutil
import sys
import time
import requests
import base64
from dotenv import load_dotenv
from datetime import datetime, timezone
from dateutil import tz

# Declare the program version
__version__ = "0.2.1"

# Load environment variables from .env file
load_dotenv()

# GitHub API details
GITHUB_REPO = "MDMAinsley/file-backup"
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
HEADERS = {'Authorization': f'token {GITHUB_TOKEN}'}

# Variables setup
tracking_file = 'files_to_track.json'

# Create and configure logger
logging.basicConfig(filename="FileBackup.log",
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    filemode='w',
                    level=logging.DEBUG)


# Hashing function to get the content hash of a file
def get_file_hash(filename):
    hasher = hashlib.sha256()  # Use SHA-256 for hashing
    with open(filename, 'rb') as f:
        while chunk := f.read(8192):  # Read in chunks to avoid memory issues
            hasher.update(chunk)
    return hasher.hexdigest()


# Get the contents of the file from GitHub
def get_github_file_content(filename):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        file_info = response.json()
        return file_info['content']  # Base64 content
    else:
        print(f"Error fetching file content for {filename}: {response.status_code}")
        return None


# Get last modified date of the GitHub file by finding the latest commit
def get_github_last_modified(filename):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits"
    params = {'path': filename, 'per_page': 1}  # Only fetch the most recent commit affecting the file
    response = requests.get(url, headers=HEADERS, params=params)

    if response.status_code == 200:
        commit_data = response.json()
        if commit_data:  # Check if the commit data is not empty
            commit_date = commit_data[0]['commit']['committer']['date']  # Get the commit date
            return commit_date  # This is in ISO 8601 format
    else:
        print(f"Error fetching last commit for {filename}: {response.status_code}")
        return None


def format_datetime(dt):
    """Format a datetime object to a human-readable string in 24-hour format."""
    # Get the user's local timezone
    local_tz = tz.tzlocal()  # Automatically detect the local timezone
    local_dt = dt.astimezone(local_tz)
    return local_dt.strftime('%d %B %Y @ %H:%M%p')  # Use %H for 24-hour format


# Function to upload a local file to GitHub
def upload_to_github(local_file, github_file):
    try:
        # Read the local file content
        with open(local_file, 'rb') as f:
            content = f.read()

        # Convert the content to Base64 encoding required by GitHub API
        encoded_content = base64.b64encode(content).decode('utf-8')

        # Check if the file exists on GitHub
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{github_file}"
        response = requests.get(url, headers=HEADERS)

        if response.status_code == 200:
            # File exists, get its SHA to update the file
            file_info = response.json()
            sha = file_info['sha']
            message = f"Update {github_file} via script"
            data = {
                "message": message,
                "content": encoded_content,
                "sha": sha
            }
        elif response.status_code == 404:
            # File doesn't exist, create a new one
            message = f"Create {github_file} via script"
            data = {
                "message": message,
                "content": encoded_content
            }
        else:
            print(f"Error checking file existence on GitHub: {response.status_code}")
            return False

        # Send PUT request to create/update the file
        response = requests.put(url, headers=HEADERS, json=data)
        if response.status_code in [200, 201]:
            print(f"Successfully uploaded {github_file} to GitHub.")
            return True
        else:
            print(f"Error uploading file to GitHub: {response.status_code}")
            return False

    except Exception as e:
        print(f"An error occurred while uploading the file: {e}")
        return False


# Compare the local and GitHub files
def compare_files(github_file, local_file):
    # Check if the local file exists
    if not os.path.exists(local_file):
        print(f"Local file {local_file} is missing. Removing from tracking.")
        return False  # Indicate that the file should be removed

    # Fetch the GitHub file content
    github_hash = get_github_file_content(github_file)
    if github_hash is None:
        print(f"GitHub file {github_file} is missing. Removing from tracking.")
        return False  # Indicate that the file should be removed

    # GitHub file content is base64-encoded, so we need to decode it
    import base64
    github_hash_decoded = hashlib.sha256(base64.b64decode(github_hash)).hexdigest()

    local_hash = get_file_hash(local_file)

    print(f"Local file hash: {local_hash}")
    print(f"GitHub file hash: {github_hash_decoded}")

    # Check if the files are identical
    if local_hash == github_hash_decoded:
        print("Files are identical. No need to update.")
        return True  # Indicate that the file is okay

    # If hashes differ, check the modification dates
    local_last_modified = os.path.getmtime(local_file)
    github_last_modified = get_github_last_modified(github_file)

    if github_last_modified is None:
        print(f"Could not retrieve last modified date from GitHub for {github_file}.")
        return True  # No need to remove if we can't get the last modified date

    # Convert local and GitHub modification dates to datetime objects
    local_datetime = datetime.fromtimestamp(local_last_modified, tz=timezone.utc)
    github_datetime = datetime.fromisoformat(github_last_modified[:-1])  # Remove 'Z' for parsing

    # Ensure github_datetime is timezone-aware
    github_datetime = github_datetime.replace(tzinfo=timezone.utc)

    print(f"Local last modified date: {format_datetime(local_datetime)}")
    print(f"GitHub last modified date: {format_datetime(github_datetime)}")

    if local_datetime > github_datetime:
        user_choice = input("Your local file is newer. Do you want to upload it to GitHub? (y/n): ")
        if user_choice.lower() == 'y':
            # Upload the local file to GitHub
            print("Uploading local version to GitHub...")
            upload_to_github(local_file, github_file)
    else:
        user_choice = input("The GitHub file is newer. Do you want to download and replace your local version? (y/n): ")
        if user_choice.lower() == 'y':
            # Download the GitHub version and replace the local file
            print("Downloading GitHub version...")
            download_github_file(github_file, local_file)

    return True  # Indicate that the file is okay


# Function to print to the console and log at the same time
def print_and_log(message_to_print, logging_func):
    # Print to the console
    print(message_to_print)
    # Call the logging function
    if callable(logging_func):
        logging_func(message_to_print)
    else:
        logging.error(f"Invalid logging function specified for message: {message_to_print}")


# Function to load settings from the JSON file
def load_settings():
    if not os.path.exists(tracking_file):
        save_settings({"do_setup": True, "whitelist": [], "files_to_track": {}})
        print_and_log("File not found. Created new default tracking file.", logging.info)
    with open(tracking_file, 'r') as f:
        settings = json.load(f)
        print_and_log("Successfully loaded tracking file.", logging.info)

    if 'do_setup' not in settings:
        settings['do_setup'] = True
        save_settings(settings)
        print_and_log("Added 'do_setup' setting.", logging.info)
    if 'whitelist' not in settings:
        settings['whitelist'] = []
        save_settings(settings)
        print_and_log("Added 'whitelist' setting.", logging.info)
    if 'files_to_track' not in settings:
        settings['files_to_track'] = {}
        save_settings(settings)
        print_and_log("Added 'do_setup' setting.", logging.info)
    return settings


# Function to save options to the JSON file
def save_settings(settings):
    with open(tracking_file, 'w') as f:
        json.dump(settings, f, indent=4)


# Function to change an option in the tracking file
def update_setting(new_setting, setting_name, setting_file):
    setting_file[setting_name] = new_setting
    save_settings(setting_file)


# Function to get the key from a value in a dictionary
def get_key_from_value(d, value):
    for key, val in d.items():
        if val == value:
            return key
    return None  # Return None if not found


# Function to track a new file and upload if not tracked
def add_file_to_tracking(settings):
    # Ask if the user wants to add files from a directory
    directory_input = input("Would you like to track files from a directory? (yes/no): ").strip().lower()

    if directory_input == 'yes':
        directory_path = input("Enter the directory path: ").strip()

        # Check if the path is a valid directory
        if os.path.isdir(directory_path):
            # List all files in the directory
            files_in_directory = os.listdir(directory_path)
            num_files = len(files_in_directory)

            # Warn if there are more than 10 files
            if num_files > 10:
                warning = input(
                    f"The directory contains {num_files} files. Do you want to proceed? (yes/no): ").strip().lower()
                if warning != 'yes':
                    print("Operation canceled.")
                    return

            # Ask for the GitHub folder name
            github_folder_name = input(
                "Enter the name of the GitHub folder where the files should be uploaded: ").strip()

            # Track each file in the directory
            for file_name in files_in_directory:
                local_file = os.path.join(directory_path, file_name)
                github_file = f"{github_folder_name}/{file_name}"  # Concatenate the folder name

                # Check if the file is already tracked
                if 'files_to_track' not in settings:
                    settings['files_to_track'] = {}

                # Check if the file is already being tracked
                possible_key = get_key_from_value(settings['files_to_track'], local_file)

                if github_file in settings['files_to_track']:
                    print(
                        f"'{github_file}' is already tracking local file '{settings['files_to_track'][github_file]}'.")
                elif possible_key is not None:
                    print(
                        f"The local file '{local_file}' is already being tracked under a different GitHub entry "
                        f"'{possible_key}'.")
                else:
                    # Upload the local file to GitHub
                    success = upload_to_github(local_file, github_file)
                    if success:
                        # Update the 'files_to_track' entry in the settings
                        settings['files_to_track'][github_file] = local_file
                        save_settings(settings)
                        print(f"Uploaded {local_file} to '{github_file}' and added it to the tracking list.")
                    else:
                        print(f"Failed to upload {local_file} to GitHub.")
        else:
            print("Invalid directory path.")
            return
    else:
        # Existing functionality for a single file
        github_file = input("Enter the GitHub file path (e.g., folder/name.filetype or name.filetype): ")
        local_file = input("Enter the local file path or return to menu with 'm': ")
        if local_file == "m":
            return

        # Check if the file is already tracked
        if 'files_to_track' not in settings:
            settings['files_to_track'] = {}

        # Get if a value appears in file to track
        possible_key = get_key_from_value(settings['files_to_track'], local_file)

        if github_file in settings['files_to_track']:
            print(f"'{github_file}' is already tracking local file '{settings['files_to_track'][github_file]}'.")
        elif possible_key is not None:
            print(
                f"The local file '{local_file}' is already being tracked under a different GitHub entry"
                f" '{possible_key}'.")
        else:
            # Upload the local file to GitHub
            success = upload_to_github(local_file, github_file)
            if success:
                # Update the 'files_to_track' entry in the settings
                settings['files_to_track'][github_file] = local_file
                save_settings(settings)
                print(f"Uploaded {local_file} and added {github_file} to the tracking list.")
            else:
                print(f"Failed to upload {local_file} to GitHub.")


# Function to clear the console on any os
def clear_console():
    # For Windows
    if os.name == 'nt':
        os.system('cls')
    # For Linux/macOS
    else:
        os.system('clear')


# Function to check for internet connection
def check_internet():
    try:
        requests.get('https://www.google.com/', timeout=5)
        return True
    except requests.ConnectionError:
        return False


# Function to add a specific reply requirement onto the input function of Python
def specific_input(question_to_ask, required_answers=None, input_type=None):
    while True:
        user_input = input(question_to_ask)

        # Type validation
        if input_type:
            try:
                # Check for integer input
                if input_type == int:
                    user_input = int(user_input)

                # Check for float input
                elif input_type == float:
                    user_input = float(user_input)

                # Check for string input
                elif input_type == str:
                    user_input = str(user_input)

                # Check for char input (ensure single character)
                elif input_type == 'char':
                    if len(user_input) != 1:
                        raise ValueError("Please enter a single character.")

                # Check for boolean input (interpret true/false)
                elif input_type == bool:
                    user_input_lower = user_input.lower()
                    if user_input_lower in ['true', 't', 'yes', 'y', '1']:
                        user_input = True
                    elif user_input_lower in ['false', 'f', 'no', 'n', '0']:
                        user_input = False
                    else:
                        raise ValueError("Please enter a valid boolean (yes/no, true/false).")
                else:
                    raise ValueError(f"Unsupported input type: {input_type}")

            except ValueError as ve:
                print(ve)
                continue

        # If RequiredAnswers is provided, ensure input matches allowed answers
        if required_answers is not None:
            if str(user_input).lower() not in [answer.lower() for answer in required_answers]:
                print(f"Please enter one of the following: {', '.join(required_answers)}")
                continue

        return user_input


# Fetch the list of files from the GitHub repository with a whitelist filter
def list_github_files(settings, whitelist=None, path=""):
    if whitelist is None:
        whitelist = []  # Default empty whitelist

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        files = response.json()  # JSON contains a list of files with their details
        file_list = []

        for file in files:
            file_path = file['path']

            # Check if the file is a whitelisted file or is inside a whitelisted directory
            is_whitelisted = any(file_path.endswith(whitelisted) or file_path.startswith(whitelisted + '/')
                                 for whitelisted in whitelist)

            if file['type'] == 'file' and not is_whitelisted:
                file_list.append(file_path)

            elif file['type'] == 'dir':
                # Recursively get nested files
                nested_files = list_github_files(settings, whitelist, file_path)
                # Only add directories that don't contain whitelisted files
                if not any(nested_file.endswith(w) or nested_file.startswith(w) for nested_file in nested_files
                           for w in whitelist):
                    file_list.extend(nested_files)

        return file_list
    else:
        print(f"Error fetching files from GitHub: {response.status_code}")
        return []


# Prompt the user to specify a save location
def choose_save_location():
    while True:
        local_file = input("Specify the save location for the file (including filename): ")
        directory = os.path.dirname(local_file)

        # Check if the directory exists, and create it if it doesn't
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory)  # Create the directory
                print(f"Directory '{directory}' created.")
            except Exception as e:
                print(f"Error creating directory: {e}")
                continue  # Prompt for the location again

        # Now check if the file already exists
        if os.path.exists(local_file):
            overwrite = input(f"{local_file} already exists. Overwrite? (y/n): ")
            if overwrite.lower() != 'y':
                print("Please specify a different file name or path.")
                continue

        return local_file


# Download the selected file from GitHub and save it locally
def download_github_file(github_file, save_location):
    if os.path.exists(save_location):
        backup_location = save_location + ".bak"
        shutil.copy2(save_location, backup_location)
        print(f"Backup created at {backup_location}")

    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{github_file}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        with open(save_location, 'wb') as file:
            file.write(response.content)
        print(f"Downloaded {github_file} to {save_location}")
        return True
    else:
        print(f"Error downloading {github_file}: {response.status_code}")
        return False


def add_github_file_to_tracking(settings):
    # Clean up tracking entries before proceeding
    whitelist = ['.gitignore', '.idea/', 'build/', 'dist/', '.spec', '.py', '.ico']
    for entry in settings['whitelist']:
        whitelist.append(entry)
    github_files = list_github_files(settings, whitelist)

    if not github_files:
        print("No files available for tracking.")
        return

    # Ask if the user wants to add files from a GitHub directory
    directory_input = input("Would you like to track files from a GitHub directory? (yes/no): ").strip().lower()

    if directory_input == 'yes':
        github_directory_path = input("Enter the GitHub directory path: ").strip()

        # Check for already tracked files
        tracked_files = settings.get('files_to_track', {})

        if not tracked_files:
            print("No files are currently being tracked from this directory.")

        # Get the files in the specified GitHub directory
        github_directory_files = [file for file in github_files if file.startswith(github_directory_path)]
        print("The specified directory contains the following file(s): ")
        for file in github_directory_files:
            if file in tracked_files:
                print(f"{file} [ALREADY TRACKED] (local copy: {tracked_files[file]})")
            else:
                print(file)

        if not github_directory_files:
            print(f"No files found in the GitHub directory '{github_directory_path}'.")
            return

        # Check if the GitHub directory has more than 10 files
        num_files_in_directory = len(github_directory_files)
        if num_files_in_directory > 10:
            warning = (input(
                f"The GitHub directory contains {num_files_in_directory} files. Do you want to proceed? (yes/no): ")
                       .strip().lower())
            if warning != 'yes':
                print("Operation canceled.")
                return

        # Ask for the local download directory
        download_directory = input("Enter the local directory path where you want to download the files or"
                                   " (m) for menu: ").strip()
        if download_directory == "m":
            return
        # Check if the download path is valid
        if os.path.isdir(download_directory):
            for github_file in github_directory_files:
                local_file_path = os.path.join(download_directory, os.path.basename(github_file))

                # Download each file from GitHub to the specified local directory
                if download_github_file(github_file, local_file_path):
                    if 'files_to_track' not in settings:
                        settings['files_to_track'] = {}

                    # Track the downloaded file
                    settings['files_to_track'][github_file] = local_file_path
                    print(f"Downloaded and tracking '{github_file}' -> '{local_file_path}'")
                else:
                    print(f"Failed to download '{github_file}'.")
        else:
            create_dir = (input(
                "The specified download directory does not exist. Would you like to create it? (yes/no): ")
                          .strip().lower())
            if create_dir == 'yes':
                os.makedirs(download_directory)
                print(f"Created directory: {download_directory}")

                # Retry downloading the files after creating the directory
                for github_file in github_directory_files:
                    local_file_path = os.path.join(download_directory, os.path.basename(github_file))

                    if download_github_file(github_file, local_file_path):
                        if 'files_to_track' not in settings:
                            settings['files_to_track'] = {}

                        # Track the downloaded file
                        settings['files_to_track'][github_file] = local_file_path
                        print(f"Downloaded and tracking '{github_file}' -> '{local_file_path}'")
                    else:
                        print(f"Failed to download '{github_file}'.")
            else:
                print("Operation canceled.")
                return
    else:
        # Check for already tracked files
        tracked_files = settings.get('files_to_track', {})
        # Display the available files
        print("Available files on GitHub:")
        for idx, file in enumerate(github_files):
            if file in tracked_files:
                print(f"{idx + 1}. {file} [ALREADY TRACKED] (local copy: {tracked_files[file]})")
            else:
                print(f"{idx + 1}. {file}")

        selection = input(f"Select a file to download (1-{len(github_files)}) or (m) for menu: ")
        if selection == "m":
            return
        selection = int(selection)
        if 1 <= selection <= len(github_files):
            github_file = github_files[selection - 1]
        else:
            print("Invalid selection.")
            return

        # Check if the file is already being tracked
        if github_file in settings.get('files_to_track', {}):
            local_copy_path = settings['files_to_track'][github_file]
            print(f"File is already being tracked, local copy @ {local_copy_path}")
            return

        local_file = choose_save_location()

        if download_github_file(github_file, local_file):
            if 'files_to_track' not in settings:
                settings['files_to_track'] = {}

            # Add the file to tracking
            settings['files_to_track'][github_file] = local_file
            save_settings(settings)
            print(f"Tracking {github_file} -> {local_file}")
        else:
            print(f"Failed to download or track the file.")


# Function to remove a file from tracking
def remove_file_from_tracking(settings):
    if 'files_to_track' not in settings or not settings['files_to_track']:
        print("No files are currently being tracked.")
        return

    # Display the currently tracked files
    print("Currently tracked files:")
    for idx, (github_file, local_file) in enumerate(settings['files_to_track'].items()):
        print(f"{idx + 1}. {github_file} (Local copy: {local_file})")

    # Prompt user to select a file to remove from tracking
    while True:
        try:
            selection = int(input(f"Select a file to remove from tracking (1-{len(settings['files_to_track'])}): "))
            if 1 <= selection <= len(settings['files_to_track']):
                github_file = list(settings['files_to_track'].keys())[selection - 1]
                break
            else:
                print(f"Please select a number between 1 and {len(settings['files_to_track'])}.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")

    # Remove from tracking
    local_file = settings['files_to_track'][github_file]
    del settings['files_to_track'][github_file]
    save_settings(settings)
    print(f"Removed {github_file} from tracking. Local copy was at {local_file}.")


# Function to remove a file from GitHub and tracking
def remove_file_from_github_and_tracking(settings):
    if 'files_to_track' not in settings or not settings['files_to_track']:
        print("No files are currently being tracked.")
        return

    # Display the currently tracked files
    print("Currently tracked files:")
    for idx, (github_file, local_file) in enumerate(settings['files_to_track'].items()):
        print(f"{idx + 1}. {github_file} (Local copy: {local_file})")

    # Prompt user to select a file to remove
    while True:
        try:
            selection = int(input(f"Select a file to remove (1-{len(settings['files_to_track'])}): "))
            if 1 <= selection <= len(settings['files_to_track']):
                github_file = list(settings['files_to_track'].keys())[selection - 1]
                break
            else:
                print(f"Please select a number between 1 and {len(settings['files_to_track'])}.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")

    # Remove from tracking
    del settings['files_to_track'][github_file]
    save_settings(settings)
    print(f"Removed {github_file} from tracking.")

    # Get the SHA of the file to delete
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{github_file}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        file_info = response.json()
        sha = file_info['sha']

        # Now we can delete the file
        delete_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{github_file}"
        data = {
            "message": f"Delete {github_file} via script",
            "sha": sha
        }
        delete_response = requests.delete(delete_url, headers=HEADERS, json=data)

        if delete_response.status_code == 200:
            print(f"Successfully removed {github_file} from GitHub.")
        else:
            print(f"Failed to remove {github_file} from GitHub:"
                  f" {delete_response.status_code} - {delete_response.json()}")
    else:
        print(f"Failed to fetch file information from GitHub: {response.status_code} - {response.json()}")


# Main program function
def main():
    if "--version" in sys.argv:
        print(f"v{__version__}")
        return
    if check_internet():
        print_and_log("Connection active.", logging.info)
    else:
        print_and_log("Offline Mode", logging.info)
    print_and_log(f"Running application version v{__version__}", logging.info)
    time.sleep(2)
    try:
        while True:
            clear_console()
            # Create or load settings file
            settings = load_settings()

            # First-time setup or file tracking changes
            if settings.get('do_setup', False):
                print_and_log("Running first time configuration.", logging.info)
                add_file_to_tracking(settings)
                update_setting(False, 'do_setup', settings)

            print("1) Check currently tracked files for changes")
            print("2) Add new file to track on Github")
            print("3) Track new file from GitHub")
            print("4) Stop tracking submenu")
            print("5) Configure whitelist")
            print("q) Exit the application")
            answer = specific_input("(1/2/3/4/5/q): ", ["1", "2", "3", "4", "5", "q"])
            if answer == "1":
                # Check if files_to_track is empty
                if not settings['files_to_track']:
                    print("No files are currently being tracked.")
                else:
                    keys_to_remove = []  # List to collect keys to remove
                    for key in list(settings['files_to_track'].keys()):  # Use list() to avoid modifying while iterating
                        print()
                        print(f"Checking file: {key}...")
                        time.sleep(1)
                        print()
                        value = settings['files_to_track'][key]
                        if not compare_files(key, value):  # If compare_files indicates removal
                            keys_to_remove.append(key)
                    # Now remove the collected keys after the iteration is done
                    for key in keys_to_remove:
                        del settings['files_to_track'][key]
                    save_settings(settings)  # Save settings after all removals
                time.sleep(2)
            elif answer == "2":
                add_file_to_tracking(settings)
                time.sleep(2)
            elif answer == "3":
                add_github_file_to_tracking(settings)
                time.sleep(2)
            elif answer == "4":
                sub_choice = specific_input(
                    "Do you want to (1) remove from tracking or (2) remove from GitHub and tracking?"
                    " or return to menu(m)? (1/2/m): ",
                    ["1", "2", "m"])
                if sub_choice == '1':
                    remove_file_from_tracking(settings)
                elif sub_choice == '2':
                    remove_file_from_github_and_tracking(settings)
                time.sleep(2)
            elif answer == "5":
                while True:
                    print(f"Current whitelist: {settings['whitelist']}")
                    print("'m' to return to menu")
                    new_entry = input("enter new whitelist entry: ")
                    if new_entry == "m":
                        break
                    else:
                        settings['whitelist'].append(new_entry)
                        save_settings(settings)
                    print("Added new entry succesfully.")
                print(f"Current state of whitelist: {settings['whitelist']}")
                time.sleep(2)
            elif answer == "q":
                break
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
