import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import requests
import base64
import winshell
import psutil
from colorama import Fore, Style, init
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
from dateutil import tz

# Declare program version
__version__ = "0.6.0"

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

# Initialize colorama
init()


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

        # Check if file is larger than 1MB
        if file_info['size'] > 1000000:  # GitHub API size limit for fetching via 'contents'
            # print("File is too large for /contents/ API. Fetching via /git/blobs/ API.")

            # Retrieve the blob SHA from the file_info
            blob_sha = file_info.get('sha')
            if not blob_sha:
                print("Error: Unable to retrieve blob SHA.")
                return None

            # Fetch blob via git/blobs using the SHA
            blob_url = f"https://api.github.com/repos/{GITHUB_REPO}/git/blobs/{blob_sha}"
            blob_response = requests.get(blob_url, headers=HEADERS)

            if blob_response.status_code == 200:
                blob_info = blob_response.json()
                return blob_info['content']  # Base64-encoded content
            else:
                print(f"Error fetching blob content for {filename}: {blob_response.status_code}")
                return None
        else:
            # For smaller files, fetch normally
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


def add_shortcut_to_startup(exe_path):
    try:
        # Ensure the executable path exists
        if not os.path.exists(exe_path):
            print("The specified executable path does not exist.")
            return

        # Get the path to the startup folder
        startup_dir = Path(winshell.startup())
        shortcut_path = startup_dir / f"{Path(exe_path).stem}.lnk"

        # Convert Path object to string for winshell.shortcut
        shortcut_path_str = str(shortcut_path)

        # Create the shortcut
        with winshell.shortcut(shortcut_path_str) as shortcut:
            shortcut.path = exe_path
            shortcut.working_directory = os.path.dirname(exe_path)
            shortcut.description = "Shortcut to File Backup Launcher"
            shortcut.icon_location = (exe_path, 0)

        print(f"Added shortcut to startup: {shortcut_path_str}")
    except Exception as e:
        print(f"Failed to add shortcut to startup: {e}")


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


def print_in_multi_colour_and_log(message_sections, logging_func=None):
    try:
        full_message = ""
        for section, color in message_sections:
            color = getattr(Fore, color.upper(), Fore.RESET)  # Get the color or reset to default
            print(color + section + Style.RESET_ALL, end="")  # Print each section in its color
            full_message += section  # Build the full message for logging

        print()  # Move to a new line after printing

        # Log the complete message if logging function is provided
        if logging_func is not None:
            if callable(logging_func):
                logging_func(full_message)
            else:
                logging.error(f"Invalid logging function specified for message: {full_message}.")
    except AttributeError as e:
        # Log the error if an invalid color is provided
        logging.error(f"Error: {str(e)}")


# Function to load settings from the JSON file
def load_settings():
    if not os.path.exists(tracking_file):
        save_settings({"do_setup": True, "blacklist": [], 'process_watchlist': [], "files_to_track": {},
                       "file_check_interval": 60, "game_check_interval": 90, "show_console_if_input": True})
        print_and_log("File not found. Created new default tracking file.", logging.info)
    with open(tracking_file, 'r') as f:
        settings = json.load(f)
        print_and_log("Successfully loaded tracking file.", logging.info)

    # Check if needed settings exist and create them if not
    if 'do_setup' not in settings:
        settings['do_setup'] = True
        save_settings(settings)
        print_and_log("Added 'do_setup' setting.", logging.info)
    if 'blacklist' not in settings:
        settings['blacklist'] = []
        save_settings(settings)
        print_and_log("Added 'blacklist' setting.", logging.info)
    if 'process_watchlist' not in settings:
        settings['process_watchlist'] = []
        save_settings(settings)
        print_and_log("Added 'process_watchlist' setting.", logging.info)
    if 'files_to_track' not in settings:
        settings['files_to_track'] = {}
        save_settings(settings)
        print_and_log("Added 'do_setup' setting.", logging.info)
    if 'file_check_interval' not in settings:
        settings['file_check_interval'] = 60
        save_settings(settings)
        print_and_log("Added 'file_check_interval' setting.", logging.info)
    if 'game_check_interval' not in settings:
        settings['game_check_interval'] = 15
        save_settings(settings)
        print_and_log("Added 'game_check_interval' setting.", logging.info)
    if 'show_console_if_input' not in settings:
        settings['show_console_if_input'] = True
        save_settings(settings)
        print_and_log("Added 'show_console_if_input' setting.", logging.info)

    # Check if obsolete settings exists and remove them
    if 'whitelist' in settings:
        del settings['whitelist']
        save_settings(settings)
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


# Function to check if a file is already tracked and handle upload logic
def handle_file_tracking(settings, local_file, github_file):
    # Ensure the tracking dictionary exists
    if 'files_to_track' not in settings:
        settings['files_to_track'] = {}

    # Check if the file is already being tracked
    possible_key = get_key_from_value(settings['files_to_track'], local_file)

    if github_file in settings['files_to_track']:
        print(f"'{github_file}' is already tracking local file '{settings['files_to_track'][github_file]}'.")
    elif possible_key is not None:
        print(f"The local file '{local_file}' is already being tracked under a different GitHub entry"
              f" '{possible_key}'.")
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


# Function to track a new file and upload if not tracked
def add_file_to_tracking(settings):
    # Ask if the user wants to add files from a directory
    directory_input = input("Would you like to track files from a directory? (yes/no): ").strip().lower()

    if directory_input == 'yes':
        directory_path = input("Enter the directory path: ").strip()

        # Check if the path is a valid directory
        if os.path.isdir(directory_path):
            files_in_directory = os.listdir(directory_path)
            num_files = len(files_in_directory)

            # Warn if there are more than 10 files
            if num_files > 10:
                warning = (input(f"The directory contains {num_files} files. Do you want to proceed? (yes/no): ")
                           .strip().lower())
                if warning != 'yes':
                    print("Operation canceled.")
                    return

            # Ask for the GitHub folder name
            github_folder_name = (input("Enter the name of the GitHub folder where the files should be uploaded: ")
                                  .strip())

            # Track each file in the directory
            for file_name in files_in_directory:
                local_file = os.path.join(directory_path, file_name)
                github_file = f"{github_folder_name}/{file_name}"  # Concatenate the folder name
                handle_file_tracking(settings, local_file, github_file)

        else:
            print("Invalid directory path.")
            return
    else:
        # Existing functionality for a single file
        github_file = input("Enter the GitHub file path (e.g., folder/name.filetype or name.filetype): ")
        local_file = input("Enter the local file path (or type 'menu' to go back): ")
        if local_file == "menu":
            return

        handle_file_tracking(settings, local_file, github_file)


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
def specific_input(question_to_ask, required_answers=None, input_type=None, exit_text=None):
    while True:
        user_input = input(question_to_ask)
        if exit_text is not None:
            for key in exit_text:
                if user_input == key:
                    return user_input

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


# Fetch the list of files from the GitHub repository with a blacklist filter
def list_github_files(settings, blacklist=None, path=""):
    if blacklist is None:
        blacklist = []  # Default empty blacklist

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 200:
        files = response.json()  # JSON contains a list of files with their details
        file_list = []

        for file in files:
            file_path = file['path']

            # Check if the file is a blacklisted file or is inside a blacklisted directory
            is_blacklisted = any(file_path.endswith(blacklisted) or file_path.startswith(blacklisted + '/')
                                 for blacklisted in blacklist)

            if file['type'] == 'file' and not is_blacklisted:
                file_list.append(file_path)

            elif file['type'] == 'dir':
                # Recursively get nested files
                nested_files = list_github_files(settings, blacklist, file_path)
                # Only add directories that don't contain blacklisted files
                if not any(nested_file.endswith(w) or nested_file.startswith(w) for nested_file in nested_files
                           for w in blacklist):
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


def list_tracked_files(tracked_files, github_files):
    """Display tracked and untracked files."""
    for idx, file in enumerate(github_files):
        if file in tracked_files:
            print(f"{idx + 1}. {file} [ALREADY TRACKED] (local copy: {tracked_files[file]})")
        else:
            print(f"{idx + 1}. {file}")


def handle_directory_tracking(settings, github_files):
    """Handle tracking files from a specified GitHub directory."""
    unique_directories = {file.split('/')[0] for file in github_files if '/' in file}

    print("The GitHub contains the following directories:")
    for directory in unique_directories:
        print(directory)

    github_directory_path = input("Enter the GitHub directory path: ").strip()
    tracked_files = settings.get('files_to_track', {})

    if not tracked_files:
        print("No files are currently being tracked from this directory.")

    # Get files in the specified GitHub directory
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
        warning = input(f"The GitHub directory contains {num_files_in_directory} files."
                        f" Do you want to proceed? (yes/no): ").strip().lower()
        if warning != 'yes':
            print("Operation canceled.")
            return

    # Ask for the local download directory
    download_directory = (input("Enter the local directory path where you want to download the files or (m) for menu: ")
                          .strip())
    if download_directory == "m":
        return

    # Check if the download path is valid or create it
    if not os.path.isdir(download_directory):
        create_dir = (input("The specified download directory does not exist. Would you like to create it? (yes/no): ")
                      .strip().lower())
        if create_dir == 'yes':
            os.makedirs(download_directory)
            print(f"Created directory: {download_directory}")
        else:
            print("Operation canceled.")
            return

    # Download each file from GitHub to the specified local directory
    for github_file in github_directory_files:
        local_file_path = os.path.join(download_directory, os.path.basename(github_file))

        if download_github_file(github_file, local_file_path):
            settings.setdefault('files_to_track', {})[github_file] = local_file_path
            print(f"Downloaded and tracking '{github_file}' -> '{local_file_path}'")
        else:
            print(f"Failed to download '{github_file}'.")


def handle_file_selection(settings, github_files):
    """Handle the selection and downloading of a single GitHub file."""
    tracked_files = settings.get('files_to_track', {})
    list_tracked_files(tracked_files, github_files)

    selection = input(f"Select a file to download (1-{len(github_files)}) (or type 'menu' to go back): ")
    if selection == "menu":
        return

    selection = int(selection)
    if 1 <= selection <= len(github_files):
        github_file = github_files[selection - 1]
    else:
        print("Invalid selection.")
        return

    if github_file in tracked_files:
        local_copy_path = tracked_files[github_file]
        print(f"File is already being tracked, local copy @ {local_copy_path}")
        return

    local_file = choose_save_location()

    if download_github_file(github_file, local_file):
        settings.setdefault('files_to_track', {})[github_file] = local_file
        save_settings(settings)
        print(f"Tracking {github_file} -> {local_file}")
    else:
        print(f"Failed to download or track the file.")


def add_github_file_to_tracking(settings):
    # Clean up tracking entries before proceeding
    blacklist = ['.gitignore', '.idea/', 'build/', 'dist/', '.spec', '.py', '.ico']
    blacklist.extend(settings['blacklist'])
    github_files = list_github_files(settings, blacklist)

    if not github_files:
        print("No files available for tracking.")
        return

    # Ask if the user wants to add files from a GitHub directory
    directory_input = input("Would you like to track files from a GitHub directory? (yes/no): ").strip().lower()

    if directory_input == 'yes':
        handle_directory_tracking(settings, github_files)
    else:
        handle_file_selection(settings, github_files)


def display_tracked_files(settings):
    """Display currently tracked files."""
    print("Currently tracked files:")
    for idx, (github_file, local_file) in enumerate(settings['files_to_track'].items()):
        print(f"{idx + 1}. {github_file} (Local copy: {local_file})")


def prompt_file_selection(num_files):
    """Prompt the user to select a file from tracked files."""
    while True:
        try:
            selection = int(input(f"Select a file to remove (1-{num_files}): "))
            if 1 <= selection <= num_files:
                return selection - 1  # Adjust for zero-based index
            else:
                print(f"Please select a number between 1 and {num_files}.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")


def remove_file_from_tracking(settings):
    """Remove a file from tracking without deleting it from GitHub."""
    if 'files_to_track' not in settings or not settings['files_to_track']:
        print("No files are currently being tracked.")
        return

    display_tracked_files(settings)

    selection_index = prompt_file_selection(len(settings['files_to_track']))
    github_file = list(settings['files_to_track'].keys())[selection_index]
    local_file = settings['files_to_track'][github_file]

    # Remove from tracking
    del settings['files_to_track'][github_file]
    save_settings(settings)
    print(f"Removed {github_file} from tracking. Local copy was at {local_file}.")


def remove_file_from_github_and_tracking(settings):
    """Remove a file from GitHub and tracking."""
    if 'files_to_track' not in settings or not settings['files_to_track']:
        print("No files are currently being tracked.")
        return

    display_tracked_files(settings)

    selection_index = prompt_file_selection(len(settings['files_to_track']))
    github_file = list(settings['files_to_track'].keys())[selection_index]

    # Remove from tracking
    del settings['files_to_track'][github_file]
    save_settings(settings)
    print(f"Removed {github_file} from tracking.")

    # Get the SHA of the file to delete from GitHub
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
            print(
                f"Failed to remove {github_file} from GitHub: {delete_response.status_code} - {delete_response.json()}")
    else:
        print(f"Failed to fetch file information from GitHub: {response.status_code} - {response.json()}")


def check_and_launch_background_process():
    app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    process_name = "FileBackup_Background.exe"
    app_exe_path = os.path.join(app_dir, process_name)
    print(f"Checking if {process_name} is currently running.")
    # Check if the process is running
    game_running = any(process.name() == process_name for process in psutil.process_iter())
    if game_running:
        print(f"{process_name} is already running.")
    else:
        print(f"{process_name} is not running. Launching now...")
        try:
            # Launch the background process in a new console window
            subprocess.Popen([app_exe_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            print(f"{process_name} has been launched.")
        except Exception as e:
            print(f"Failed to launch {process_name}: {e}")


def add_to_blacklist(settings):
    print(f"Current Blacklist: {settings['blacklist']}")
    while True:
        new_entry = input("Enter new blacklist entry (or type 'menu' to go back): ")
        if new_entry == "menu":
            break
        else:
            settings['blacklist'].append(new_entry)
            save_settings(settings)
        print("Added new entry succesfully.")
        print(f"Current Blacklist: {settings['blacklist']}")


def remove_from_blacklist(settings):
    while True:
        print("\nCurrent Blacklist:")
        for idx, entry in enumerate(settings['blacklist'], start=1):
            print(f"{idx}. {entry}")

        try:
            selection = input("Select the entry number to remove (or type 'menu' to go back): ")
            if selection == "menu":
                break

            # Convert selection to an integer
            entry_index = int(selection) - 1

            if 0 <= entry_index < len(settings['blacklist']):
                entry_to_remove = settings['blacklist'][entry_index]
                settings['blacklist'].remove(entry_to_remove)
                save_settings(settings)
                print(f"Removed '{entry_to_remove}' successfully.")
            else:
                print("Invalid selection. Please select a valid entry number.")

        except ValueError:
            print("Invalid input. Please enter a valid number.")


def remove_from_process_watchlist(settings):
    while True:
        print("\nCurrent Process Watchlist:")
        for idx, entry in enumerate(settings['process_watchlist'], start=1):
            print(f"{idx}. {entry}")
        selection = input("Select the entry number to remove (or type 'menu' to go back): ")
        if selection.lower() == "menu":
            break

        try:
            entry_index = int(selection) - 1

            if 0 <= entry_index < len(settings['process_watchlist']):
                entry_to_remove = settings['process_watchlist'][entry_index]
                settings['process_watchlist'].remove(entry_to_remove)
                save_settings(settings)
                print(f"Removed '{entry_to_remove}' successfully.")
            else:
                print("Invalid selection. Please select a valid entry number.")

        except ValueError:
            print("Invalid input. Please enter a valid number.")


def extract_app_name_from_path(executable_path):
    directory = os.path.dirname(executable_path)
    file_name = os.path.basename(executable_path)
    folder_name = os.path.basename(directory)

    non_descriptive_folders = ["bin", "debug", "release", "distribution", "thirdparty", "Binaries", "Win64",
                               "binaries", "win64", "usermods", "Redistributables", "en-us", "Engine",
                               "Extras", "redist", "Redist", "vcred", "VCRed", "Support", "support",
                               "VS2010Runtime", "VS2012Runtime", "VS2015Runtime", "VS2017Runtime"]

    if folder_name.lower() in non_descriptive_folders:
        parent_directory = os.path.dirname(directory)
        app_name = os.path.basename(parent_directory)
        if app_name.lower() in non_descriptive_folders:
            grandparent_directory = os.path.dirname(parent_directory)
            app_name = os.path.basename(grandparent_directory)
    else:
        app_name = folder_name

    app_name = clean_app_name(app_name, file_name)
    return f"{app_name} - {file_name}" if app_name else file_name


def clean_app_name(app_name, file_name):
    app_name = re.sub(r'^(installer|launcher|service|setup|client|app|application)', '', app_name,
                      flags=re.IGNORECASE).strip()
    app_name = re.sub(r'[\s_-]+', ' ', app_name).strip()
    return app_name or file_name


def get_installed_apps(search_paths=None, blacklist=None):
    if blacklist is None:
        blacklist = []

    installed_apps = {}
    if search_paths:
        for path in search_paths:
            installed_apps.update(find_executables_in_path(path, blacklist))
    return installed_apps


def find_executables_in_path(path, blacklist=None):
    if blacklist is None:
        blacklist = []

    executables = {}
    for root, dirs, files in os.walk(path):
        for file in files:
            if not any(word in file for word in blacklist):
                if file.endswith('.exe'):
                    full_path = os.path.join(root, file)
                    app_name = extract_app_name_from_path(full_path)
                    special_name = app_name
                    executables[special_name] = file
    return executables


def fetch_game_processes():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/process-list.json"
    response = requests.get(url)

    if response.status_code == 200:
        content_base64 = response.json().get('content', '')
        if content_base64:
            content_json = base64.b64decode(content_base64).decode('utf-8')
            return json.loads(content_json)
        else:
            print("No content found in the file")
            return {}
    else:
        print("Failed to fetch game processes")
        return {}


def search_game_process(game_name, game_process_list):
    game_name = game_name.lower().strip()
    matched_processes = {}

    for game, process in game_process_list.items():
        normalized_game_name = game.lower().strip()
        if game_name in normalized_game_name:
            matched_processes[game] = process

    return matched_processes


def show_game_selection(matched_games):
    if matched_games:
        print("Found the following game matches:")
        for idx, (game, exe) in enumerate(matched_games.items(), 1):
            print(f"{idx}. {game} - {exe}")
        choice = input("Select a game by number (or press ENTER to skip): ")
        if choice.isdigit() and 0 < int(choice) <= len(matched_games):
            selected_game = list(matched_games.keys())[int(choice) - 1]
            return matched_games[selected_game]
    return None


def add_to_process_watchlist(settings):
    print()
    print(f"Current process watchlist: {settings['process_watchlist']}")

    search_paths = []
    blacklist = ['Microsoft.NET.', 'Microsoft .NET']
    new_entry = input("Enter the name of the game or app to search for: ")

    while True:
        additional_path = input("Enter an additional path to search for executables (or leave empty to skip): ")
        if additional_path:
            search_paths.append(additional_path)
        else:
            break

    print("Searching user-specified paths...")
    installed_apps = get_installed_apps(search_paths, blacklist)

    print("Fetching processes from GitHub...")
    github_processes = fetch_game_processes()

    # Combine installed apps and GitHub processes
    combined_processes = {**installed_apps, **github_processes}

    # Print the result as JSON
    # print(json.dumps(combined_processes, indent=2))

    matched_entries = search_game_process(new_entry, combined_processes)

    if matched_entries:
        selected_process = show_game_selection(matched_entries)
        if selected_process is not None:
            settings['process_watchlist'].append(selected_process)
            save_settings(settings)
            print("Added new entry successfully.")
        else:
            print("No process selected.")
    else:
        print("No matches found in the process list.")


def check_files(settings):
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


def adjust_background_app_sleep_times(settings, setting_to_edit):
    if not settings[setting_to_edit]:
        print("No time currently set.")
    else:
        print(f"Current sleep time for {setting_to_edit} is set to: {settings[setting_to_edit]} minutes")
        new_time = specific_input("Enter the new sleep time in minutes (or type 'menu' to go back): ",
                                  None, int, ['menu', 'm'])
        if new_time == "menu" or new_time == "m":
            return
        else:
            settings[setting_to_edit] = new_time
            save_settings(settings)
            print(f"Succesfully update {setting_to_edit} to {new_time} minutes.")


def toggle_show_console_if_input_required(settings):
    if 'show_console_if_input' not in settings:
        print_and_log("'show_console_if_input' not found in the settings file.", logging.error)
    else:
        current_value = bool(settings['show_console_if_input'])
        if current_value:
            settings['show_console_if_input'] = False
        else:
            settings['show_console_if_input'] = True
        save_settings(settings)
        print_and_log(f"'show_console_if_input' setting updated to: [{settings['show_console_if_input']}]",
                      logging.info)


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
    check_and_launch_background_process()
    time.sleep(2)
    try:
        while True:
            clear_console()
            # Create or load settings file
            settings = load_settings()

            # First-time setup or file tracking changes
            if settings.get('do_setup', False):
                print_and_log("Running first time configuration.", logging.info)
                app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                launcher_exe_path = os.path.join(app_dir, "FileBackup_Background.exe")
                add_shortcut_to_startup(launcher_exe_path)
                check_and_launch_background_process()
                update_setting(False, 'do_setup', settings)

            print_in_multi_colour_and_log([("1)", "red"), (" Configure File Tracking.\n", "reset"),
                                           ("2)", "green"), (" Configure Process Watching.\n", "reset"),
                                           ("3)", "blue"), (" Configure Settings.\n", "reset"),
                                           ("q)", "yellow"), (" Exit the application.", "reset")])
            answer = specific_input("(1/2/3/quit): ", required_answers=['1', '2', '3', 'q', 'quit'],
                                    exit_text=['quit', 'q'])
            if answer == "q" or answer == "quit":
                break
            elif answer == "1":
                print_in_multi_colour_and_log([("   1)", "red"), (" Check tracked files for changes.\n", "reset"),
                                               ("   2)", "green"), (" Track new file ON GitHub.\n", "reset"),
                                               ("   3)", "blue"), (" Track new file FROM GitHub.\n", "reset"),
                                               ("   4)", "magenta"), (" Remove file from Local tracking.\n", "reset"),
                                               ("   5)", "cyan"), (" Remove file from Local & GitHub tracking.\n",
                                                                   "reset"),
                                               ("   6)", "lightred_ex"), (" Configure search Blacklist.\n", "reset"),
                                               ("   m)", "yellow"), (" Return to Main Menu.", "reset")])
                sub_answer = specific_input("   (1/2/3/4/5/6/menu): ", ["1", "2", "3", "4", "5", "6", "m", "menu"])
                if sub_answer == "m" or sub_answer == "menu":
                    print("Returning to Main Menu...")
                elif sub_answer == "1":
                    check_files(settings)
                elif sub_answer == "2":
                    add_file_to_tracking(settings)
                elif sub_answer == "3":
                    add_github_file_to_tracking(settings)
                elif sub_answer == "4":
                    remove_file_from_tracking(settings)
                elif sub_answer == "5":
                    remove_file_from_github_and_tracking(settings)
                elif sub_answer == "6":
                    print_in_multi_colour_and_log([("      1)", "red"), (" Add entry to Blacklist.\n", "reset"),
                                                   ("      2)", "green"), (" Remove entry from Blacklist.\n", "reset"),
                                                   ("      m)", "yellow"), (" Return to Main Menu.", "reset")])
                    sub_menu_answer = specific_input("         (1/2/menu): ", ["1", "2", "m", "menu"])
                    if sub_menu_answer == "m" or sub_menu_answer == "menu":
                        print("Returning to Main Menu...")
                    elif sub_menu_answer == "1":
                        add_to_blacklist(settings)
                    elif sub_menu_answer == "2":
                        remove_from_blacklist(settings)
            elif answer == "2":
                print_in_multi_colour_and_log([("   1)", "red"), (" Create entry in Process Watchlist.\n", "reset"),
                                               ("   2)", "green"), (" Remove entry in Process Watchlist.\n", "reset"),
                                               ("   3)", "blue"), (" Adjust sleep time for File Checking.\n", "reset"),
                                               ("   4)", "magenta"), (" Adjust sleep time for Process Checking.\n",
                                                                      "reset"),
                                               ("   m)", "yellow"), (" Return to Main Menu.", "reset")])
                sub_answer = specific_input("     (1/2/3/4/menu): ", ["1", "2", "3", "4", "m", "menu"])
                if sub_answer == "m" or sub_answer == "menu":
                    print("Returning to Main Menu...")
                elif sub_answer == "1":
                    add_to_process_watchlist(settings)
                elif sub_answer == "2":
                    remove_from_process_watchlist(settings)
                elif sub_answer == "3":
                    adjust_background_app_sleep_times(settings, 'file_check_interval')
                elif sub_answer == "4":
                    adjust_background_app_sleep_times(settings, 'game_check_interval')
            elif answer == "3":
                while True:
                    print_in_multi_colour_and_log([("   1)", "red"),
                                                   (f" Toggle show background console only when input is required. "
                                                    f"Currently: [{settings['show_console_if_input']}]\n", "reset"),
                                                   ("   2)", "green"), (" View Tracked Files.\n", "reset"),
                                                   ("   3)", "blue"), (" View Process Watchlist.\n", "reset"),
                                                   ("   4)", "magenta"), (" View Blacklist.\n", "reset"),
                                                   ("   m)", "yellow"), (" Return to Main Menu.", "reset")])
                    sub_answer = specific_input("     (1/2/3/4/menu): ", ["1", "2", "3", "4", "m", "menu"])
                    print()
                    if sub_answer == "m" or sub_answer == "menu":
                        print("Returning to Main Menu...")
                        break
                    elif sub_answer == "1":
                        toggle_show_console_if_input_required(settings)
                    elif sub_answer == "2":
                        if 'files_to_track' not in settings:
                            print_and_log("'files_to_track' not found in the settings file.", logging.error)
                        else:
                            print_and_log(f"Currently tracked files: {settings['files_to_track']}", logging.info)
                    elif sub_answer == "3":
                        if 'process_watchlist' not in settings:
                            print_and_log("'process_watchlist' not found in the settings file.", logging.error)
                        else:
                            print_and_log(f"Processes in the watchlist: {settings['process_watchlist']}", logging.info)
                    elif sub_answer == "4":
                        if 'blacklist' not in settings:
                            print_and_log("'blacklist' not found in the settings file.", logging.error)
                        else:
                            print_and_log(f"Current Blacklist: {settings['blacklist']}", logging.info)
                    print()
            time.sleep(2)
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
