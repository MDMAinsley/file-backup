import os
import shutil
import subprocess
import sys
import time

application_name = "FileBackup_Data.exe"
launcher_name = "FileBackup_Launcher.exe"


# Function to replace the outdated files
def replace_files(extract_folder, app_dir):
    # Replace GF_Launcher and GF_Data
    new_launcher_path = os.path.join(extract_folder, launcher_name)
    new_data_path = os.path.join(extract_folder, application_name)

    current_launcher_path = os.path.join(app_dir, launcher_name)
    current_data_path = os.path.join(app_dir, application_name)

    if os.path.exists(new_launcher_path):
        shutil.move(new_launcher_path, current_launcher_path)
        # print("UPDATER: GF_Launcher.exe replaced.")

    if os.path.exists(new_data_path):
        shutil.move(new_data_path, current_data_path)
        # print("UPDATER: GF_Data.exe replaced.")


# Function to remove the update zip and temp folder
def cleanup(extract_folder, zip_file):
    try:
        # Delete the extracted folder and zip file
        if os.path.exists(extract_folder):
            shutil.rmtree(extract_folder)
            # print(f"UPDATER: Deleted extracted folder {extract_folder}.")
        if os.path.exists(zip_file):
            os.remove(zip_file)
    except Exception as e:
        print(f"Error during update cleanup: {e}")


# Function to clear the console on any os
def clear_console():
    # For Windows
    if os.name == 'nt':
        os.system('cls')
    # For Linux/macOS
    else:
        os.system('clear')


# Main Function
def main():
    app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    extract_folder = sys.argv[1]  # Passed from Launcher
    zip_file = os.path.join(app_dir, os.path.basename(extract_folder).replace("update_", "v") + ".zip")

    max_retries = 5
    retry_delay = 5  # seconds

    try:
        for attempt in range(max_retries):
            try:
                # Replace launcher and data files
                replace_files(extract_folder, app_dir)

                # Clean up the update folder and zip file
                cleanup(extract_folder, zip_file)

                # Restart the updated application
                new_launcher_path = os.path.join(app_dir, launcher_name)
                subprocess.Popen([new_launcher_path])

                print("Updated successfully.")
                time.sleep(1)
                clear_console()
                sys.exit(0)  # Exit updater after successful update

            except PermissionError as e:
                if e.winerror == 32:  # WinErr32: File in use or syncing
                    print(f"Possible OneDrive/Cloud Service sync in progress,"
                          f" waiting and retrying... ({attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)  # Wait before retrying
                else:
                    raise  # Rethrow other permission errors

        # After retrying max_retries times, give up and inform the user
        print("Error: Wait for syncing to finish and run again.")
        sys.exit(1)

    except Exception as e:
        print(f"Error during update: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
