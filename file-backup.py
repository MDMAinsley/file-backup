import os
import requests
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# GitHub API details
GITHUB_REPO = "MDMAinsley/file-backup"
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
HEADERS = {'Authorization': f'token {GITHUB_TOKEN}'}


def get_github_file_version(filename):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        # File exists, returning the SHA or version tag
        file_data = response.json()
        return file_data['sha']
    else:
        return None


def get_local_file_version(filename):
    # Assuming the local file has a version stored in its metadata or separate version file
    version_file = f"{filename}.version"
    if os.path.exists(version_file):
        with open(version_file, 'r') as vf:
            return vf.read().strip()
    return None


def compare_versions(local_file, github_file):
    local_version = get_local_file_version(local_file)
    github_version = get_github_file_version(github_file)

    if local_version != github_version:
        print(f"New version available for {local_file}.")
        return True
    else:
        print(f"{local_file} is up to date.")
        return False


# Example: Check if a file needs an update
if compare_versions("savegame.dat", "path/to/savegame.dat"):
    # Prompt the user to download
    print("You can download the new version.")
    input("Press ENTER to exit...")
