import os
import shutil
import subprocess
import sys
import zipfile
import requests


owner_name = "MDMAinsley"
repo_name = "file-backup"
application_name = "FileBackup_Data.exe"
updater_name = "FileBackup_Updater.exe"


# Function to get the latest version tag from GitHub API
def get_latest_version(latest_version_url):
    response = requests.get(latest_version_url)
    response.raise_for_status()
    latest_release = response.json()
    return latest_release['tag_name'].strip()  # Trim any extra spaces


# Function to download the update zip file
def download_update_zip(download_url, download_path):
    response = requests.get(download_url, stream=True)
    response.raise_for_status()
    with open(download_path, 'wb') as zip_file:
        shutil.copyfileobj(response.raw, zip_file)


# Function to extract the zip file to a versioned folder
def extract_zip(zip_file, extract_to):
    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(extract_to)


# Function to normalize version by stripping the 'v' prefix
def normalize_version(version):
    return version.lstrip('v')  # Remove the "v" if it exists


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


# Main Function
def main():
    app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    app_exe_path = os.path.join(app_dir, application_name)
    latest_version_url = f"https://api.github.com/repos/{owner_name}/{repo_name}/releases/latest"
    updater_path = os.path.join(app_dir, updater_name)

    try:
        # Get the current and latest version
        current_version_raw = subprocess.run([app_exe_path, "--version"], capture_output=True, text=True).stdout.strip()
        current_version = normalize_version(current_version_raw)
        latest_version_raw = get_latest_version(latest_version_url)
        latest_version = normalize_version(latest_version_raw)

        if current_version != latest_version:
            if specific_input(f"Update v{latest_version} is available, would you like to update? (y/n): ",
                              ["y", "Y", "n", "N"]).lower() == "y":
                print("Starting Update...")
                # Find the download URL for the zip asset from the latest release
                response = requests.get(latest_version_url)
                latest_release = response.json()
                # Example of finding the zip file in assets
                target_asset_name = f"v{latest_version_raw}.zip"
                download_url = None
                for asset in latest_release['assets']:
                    if target_asset_name in asset['name']:
                        download_url = asset['browser_download_url']
                        break
                if not download_url:
                    raise Exception(f"Launcher could not find zip file for version {latest_version}")
                # Download the zip file
                zip_file_path = os.path.join(app_dir, target_asset_name)
                download_update_zip(download_url, zip_file_path)
                # Extract to a versioned folder
                extract_to = os.path.join(app_dir, f"update_{latest_version_raw}")
                extract_zip(zip_file_path, extract_to)
                # print(f"LAUNCHER: Extracted update to {extract_to}")
                # Replace Updater
                new_updater_path = os.path.join(extract_to, updater_name)
                shutil.copy(new_updater_path, updater_path)
                # print("LAUNCHER: GF_Updater.exe replaced.")
                # Close Launcher and start Updater to handle the rest
                # print("LAUNCHER: Starting GF_Updater...")
                subprocess.Popen([updater_path, extract_to])
                sys.exit(0)
            else:
                print("Skipping update (not recommended)...")
                subprocess.run([app_exe_path], check=True)
        else:
            print("No update available. Starting application...")
            subprocess.run([app_exe_path], check=True)

    except requests.ConnectionError:
        print("No Internet Connection. Starting application in Offline Mode...")
        subprocess.run([app_exe_path], check=True)
    except Exception as e:
        print(f"Error during launch: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
