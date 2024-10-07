import base64
import ctypes
import datetime
import hashlib
import json
import logging
import os
import shutil
import time
import threading
import pystray
import psutil
import requests
from pystray import MenuItem as Item
from PIL import Image
from dotenv import load_dotenv
from dateutil import tz
from datetime import datetime, timezone


# Load environment variables from .env file
load_dotenv()

# GitHub API details
GITHUB_REPO = "MDMAinsley/file-backup"
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
HEADERS = {'Authorization': f'token {GITHUB_TOKEN}'}

# Variable setup
game_was_opened = False
game_check_notification = False
tracking_file = 'files_to_track.json'
console_hidden = False
file_check_done = False
monitor_check_done = True
first_run_check = True
file_check_active = False
game_check_active = False


# Function to print to the console and log at the same time
def print_and_log(message_to_print, logging_func):
    # Print to the console
    print(message_to_print)
    # Call the logging function
    if callable(logging_func):
        logging_func(message_to_print)
    else:
        logging.error(f"Invalid logging function specified for message: {message_to_print}")


# Function to save options to the JSON file
def save_settings(settings):
    with open(tracking_file, 'w') as f:
        json.dump(settings, f, indent=4)


# Function to load settings from the JSON file
def load_settings(silent=False):
    if not os.path.exists(tracking_file):
        save_settings({"do_setup": True, "blacklist": [], 'process_watchlist': [], "files_to_track": {},
                       "file_check_interval": 60, "game_check_interval": 90, "show_console_if_input": True})
        print_and_log("File not found. Created new default tracking file.", logging.info)
    with open(tracking_file, 'r') as f:
        settings = json.load(f)
        if not silent:
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


# Hashing function to get the content hash of a file
def get_file_hash(filename):
    hasher = hashlib.sha256()  # Use SHA-256 for hashing
    with open(filename, 'rb') as f:
        while chunk := f.read(8192):  # Read in chunks to avoid memory issues
            hasher.update(chunk)
    return hasher.hexdigest()


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


# Compare the local and GitHub files
def compare_files(github_file, local_file, show_console_for_input=False):
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
        if show_console_for_input:
            if console_hidden:
                show_console()
        if user_choice.lower() == 'y':
            # Upload the local file to GitHub
            print("Uploading local version to GitHub...")
            upload_to_github(local_file, github_file)
    else:
        user_choice = input("The GitHub file is newer. Do you want to download and replace your local version? (y/n): ")
        if show_console_for_input:
            if console_hidden:
                show_console()
        if user_choice.lower() == 'y':
            # Download the GitHub version and replace the local file
            print("Downloading GitHub version...")
            download_github_file(github_file, local_file)

    return True  # Indicate that the file is okay


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


def format_datetime(dt):
    """Format a datetime object to a human-readable string in 24-hour format."""
    # Get the user's local timezone
    local_tz = tz.tzlocal()  # Automatically detect the local timezone
    local_dt = dt.astimezone(local_tz)
    return local_dt.strftime('%d %B %Y @ %H:%M%p')  # Use %H for 24-hour format


# Background file check function
def check_files():
    print()
    global file_check_active, game_check_active, first_run_check
    while True:
        if not game_check_active:
            file_check_active = True
            print()
            settings = load_settings(True)
            file_check_interval = settings['file_check_interval'] * 60
            console_print("Checking for file changes...", settings['show_console_if_input'])
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
                    # If compare_files indicates removal
                    if not compare_files(key, value, settings['show_console_if_input']):
                        keys_to_remove.append(key)
                # Now remove the collected keys after the iteration is done
                for key in keys_to_remove:
                    del settings['files_to_track'][key]
                save_settings(settings)  # Save settings after all removals
            print("Check complete!")
            print("Hiding the console until the next check.")
            print("Console can be made visible via the system tray icon.")
            time.sleep(5)
            file_check_active = False
            hide_console()
            if first_run_check:
                first_run_check = False
            time.sleep(file_check_interval)  # Sleep for the user-defined interval


# Function to monitor the game process
def monitor_game_process():
    while first_run_check:
        time.sleep(5)
    print("File check finished. Starting process monitor...")
    print()
    global file_check_active, game_check_active
    global game_was_opened, game_check_notification
    print("Process monitor started...")
    while True:
        if not file_check_active:
            game_check_active = True
            settings = load_settings(True)
            game_check_interval = settings['game_check_interval'] * 60
            console_print("Starting process watchlist check...", settings['show_console_if_input'])
            if not settings['process_watchlist']:
                print("No processes are in the watchlist")
            else:
                for process_name in settings['process_watchlist']:
                    print()
                    print(f"Checking if {process_name} is currently running.")
                    # Check if the process is running
                    game_running = any(process.name() == process_name for process in psutil.process_iter())
                    if game_running:
                        if not game_was_opened:
                            print(f"{process_name} has been opened.")
                            game_was_opened = True  # Mark that the game was opened
                        else:
                            print(f"{process_name} is running.")
                            game_was_opened = True
                    else:
                        if game_was_opened:
                            print(f"{process_name} has been closed, starting backup.")
                            check_files()
                            game_was_opened = False  # Reset the flag since the game has closed
                        else:
                            print(f"{process_name} is not running.")
            print()
            print("Check complete!")
            print("Hiding the console until the next check.")
            print("Console can be made visible via the system tray icon.")
            time.sleep(5)
            game_check_active = False
            hide_console()
            time.sleep(game_check_interval)  # Check every 5 seconds


# Function to handle system tray quit
def quit_action(icon):
    icon.stop()


# Function to toggle console visibility on tray icon double-click
def toggle_console():
    if console_hidden:
        show_console()
    else:
        hide_console()


# Function to configure the tray icon and its menu
def setup_tray_icon():
    icon = pystray.Icon("File Backup")  # Name of the icon in the tray
    icon.icon = Image.open("icon.ico")
    icon.menu = pystray.Menu(
        Item('Show/Hide Console', toggle_console),
        Item('Exit', lambda: quit_action(icon))
    )
    icon.run()


# Function to hide the console window
def hide_console():
    global console_hidden
    console_handle = ctypes.windll.kernel32.GetConsoleWindow()
    if console_handle != 0:
        ctypes.windll.user32.ShowWindow(console_handle, 0)  # 0 = SW_HIDE
        console_hidden = True


# Function to show the console window
def show_console():
    global console_hidden
    console_handle = ctypes.windll.kernel32.GetConsoleWindow()
    if console_handle != 0:
        ctypes.windll.user32.ShowWindow(console_handle, 1)  # 1 = SW_SHOWNORMAL
        console_hidden = False


# Wrapper for print that ensures the console is shown if hidden
def console_print(message, show_console_for_input=False):
    global console_hidden
    if console_hidden and not show_console_for_input:
        show_console()  # Show the console if it's hidden
    print(message)


# Function to start the background tasks
def start_background_tasks():
    print("Hide this console via the System Tray (Bottom Right)\n"
          "It will open itself again when needed!")

    # Start the file check thread
    file_check_thread = threading.Thread(target=check_files, daemon=True)
    file_check_thread.start()

    # Start the game monitoring thread
    game_monitor_thread = threading.Thread(target=monitor_game_process, daemon=True)
    game_monitor_thread.start()

    # Run the tray icon in the main thread
    setup_tray_icon()


if __name__ == "__main__":
    start_background_tasks()
