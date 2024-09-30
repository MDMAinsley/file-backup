import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# GitHub API details
GITHUB_REPO = "MDMAinsley/file-backup"
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
HEADERS = {'Authorization': f'token {GITHUB_TOKEN}'}


# Get last modified date of the local file
def get_local_last_modified(filename):
    try:
        timestamp = os.path.getmtime(filename)
        return datetime.fromtimestamp(timestamp).isoformat()  # Convert timestamp to ISO format
    except FileNotFoundError:
        return None


# Get last modified date of the GitHub file by finding the latest commit
def get_github_last_modified(filename):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits"
    params = {'path': filename, 'per_page': 1}  # Only fetch the most recent commit affecting the file
    response = requests.get(url, headers=HEADERS, params=params)

    if response.status_code == 200:
        commit_data = response.json()[0]  # Get the first commit in the list
        commit_date = commit_data['commit']['committer']['date']  # ISO-8601 format
        return commit_date
    else:
        print(f"Error fetching last commit for {filename}: {response.status_code}")
        return None


# Compare the local and GitHub last modified dates
def compare_file_dates(local_file):
    local_last_modified = get_local_last_modified(local_file)
    github_last_modified = get_github_last_modified(local_file)

    if local_last_modified is None:
        print(f"Local file {local_file} does not exist.")
        return False

    if github_last_modified is None:
        print(f"Could not retrieve last modified date from GitHub for {local_file}.")
        return False

    print(f"Local last modified date: {local_last_modified}")
    print(f"GitHub last modified date: {github_last_modified}")

    # Compare the two ISO date strings
    if local_last_modified >= github_last_modified:
        print(f"{local_file} is up to date.")
        return True
    else:
        print(f"New version available for {local_file}.")
        return False


# Example usage:
filename = "test.txt"  # Replace with the file you want to test
if compare_file_dates(filename):
    print("File is up to date.")
else:
    print("A new version is available.")
