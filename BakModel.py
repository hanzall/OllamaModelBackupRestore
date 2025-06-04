import os
import json
import subprocess
from datetime import datetime
import shutil
import sys
import re
import hashlib

def get_ollama_models():
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception("Failed to run ollama list command")
        lines = result.stdout.strip().split('\n')[1:]
        models = []
        for line in lines:
            match = re.match(r'^(\S+)\s+(\S+)\s+(\d+(?:\.\d+)?\s*[TGMK]?B)', line)
            if match:
                models.append({
                    'Name': match.group(1),
                    'ID': match.group(2),
                    'Size': match.group(3)
                })
        size_units = {}
        for model in models:
            unit = model['Size'].split()[-1]
            size_units[unit] = size_units.get(unit, 0) + 1

        print("\033[35mSize Units Summary:\033[0m")
        for unit in ['TB', 'GB', 'MB', 'KB', 'B']:
            if unit in size_units:
                print(f"\033[36m{unit}: {size_units[unit]} models\033[0m")
        print()
        return models
    except Exception as e:
        print(f"Error: Failed to retrieve model list from Ollama. {str(e)}")
        sys.exit(1)

def decorate_and_pad(name, width):
    if ':' in name:
        base, params = name.split(':', 1)
        visible = f"{base}:{params}"
        decorated = f"{base}:\033[34m{params}\033[0m"
    else:
        visible = name
        decorated = name
    padding_needed = width - len(visible)
    return decorated + (" " * padding_needed)

def display_models(models):
    padding = {
        'name': max(len(model['Name']) for model in models),
        'size': max(len(model['Size']) for model in models),
        'id': max(len(model['ID']) for model in models),
        'models_per_col': (len(models) + 1) // 2
    }
    padding['col_width'] = padding['name'] + padding['size'] + padding['id'] + 29

    print("\033[36mAvailable models:\033[0m")
    for i in range(padding['models_per_col']):
        left_name = decorate_and_pad(models[i]['Name'], padding['name'])
        left = f"[\033[32m{i:2d}\033[0m] {left_name} "
        left += f"\033[33m(Size: {models[i]['Size']:<{padding['size']}}, ID: {models[i]['ID']:<{padding['id']}})\033[0m"
        right = ""
        if i + padding['models_per_col'] < len(models):
            right_idx = i + padding['models_per_col']
            right_name = decorate_and_pad(models[right_idx]['Name'], padding['name'])
            right = f"[\033[32m{right_idx:2d}\033[0m] {right_name} "
            right += f"\033[33m(Size: {models[right_idx]['Size']:<{padding['size']}}, ID: {models[right_idx]['ID']:<{padding['id']}})\033[0m"
        print(f"{left:<{padding['col_width']}}  {right}")
    print("\033[31m[ q ] Quit\033[0m")
    return padding['name']

def get_multiple_selections(total_count, prompt):
    """
    Get multiple selections from user input.
    Args:
        total_count (int): Total number of items to select from
        prompt (str): The prompt to show to user
    Returns:
        list: List of selected indices
    """
    while True:
        print("\nEnter numbers separated by commas (e.g., 1,3,5)")
        print("Enter 'a' to select all")
        print("Enter 'q' to quit")
        selection = input(prompt).strip().lower()
        
        if selection == 'q':
            print("\033[32mExiting script.\033[0m")
            sys.exit(0)
        elif selection == 'a':
            return list(range(total_count))
            
        try:
            # Split by comma and convert to integers
            indices = [int(x.strip()) for x in selection.split(',')]
            # Validate all indices
            if all(0 <= idx < total_count for idx in indices):
                return sorted(set(indices))  # Remove duplicates and sort
            else:
                print(f"Invalid selection. Please enter numbers between 0 and {total_count-1}")
        except ValueError:
            print("Invalid input. Please enter numbers separated by commas, 'a' for all, or 'q' to quit")

def get_user_selection(models):
    """Get one or multiple model selections from user."""
    indices = get_multiple_selections(
        len(models),
        f"\nSelect model number(s) (0-{len(models)-1}): "
    )
    return indices

def backup_model(model_name, max_name_length):
    ollama_base = os.getenv('OLLAMA_MODELS')
    if not ollama_base:
        print("Error: OLLAMA_MODELS environment variable not set")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(
        script_dir, 
        "ModelBakup", 
        f"{model_name.replace(':', '-')}__{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    source_manifest_file = os.path.join(ollama_base, "manifests", "registry.ollama.ai", "library", 
                                          model_name.replace(':', os.path.sep))
    manifest_dir = os.path.join(backup_dir, "manifests", "registry.ollama.ai", "library", 
                                model_name.split(':')[0])
    dest_manifest_file = os.path.join(backup_dir, "manifests", "registry.ollama.ai", "library", 
                                     model_name.replace(':', os.path.sep))

    print("Copying manifest structure...")
    os.makedirs(manifest_dir, exist_ok=True)
    try:
        shutil.copy2(source_manifest_file, dest_manifest_file)
    except Exception as e:
        print(f"Warning: Failed to copy manifest files: {str(e)}")

    try:
        with open(source_manifest_file, 'r') as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error: Failed to parse manifest.json: {str(e)}")
        sys.exit(1)

    digests = [manifest['config']['digest']]
    digests.extend(layer['digest'] for layer in manifest['layers'])

    print("Copying blobs...")
    blobs_dir = os.path.join(backup_dir, "blobs")
    os.makedirs(blobs_dir, exist_ok=True)
    for digest in digests:
        source_file = os.path.join(ollama_base, "blobs", digest.replace(':', '-'))
        dest_file = os.path.join(blobs_dir, digest.replace(':', '-'))
        if os.path.exists(source_file):
            try:
                shutil.copy2(source_file, dest_file)
            except Exception as e:
                print(f"\033[33mWarning: Failed to copy blob file: {digest}\033[0m")
                print(f"\033[31m  {str(e)}\033[0m")
        else:
            print(f"\033[33mWarning: Missing blob file: {digest}\033[0m")

    print(f"\033[32mSuccessfully backed up {model_name} to:\033[0m")
    print(f"\033[36m {backup_dir}\033[0m")
    print(f"\033[35mTo restore: Run restore mode and select the backup folder.\033[0m")

def list_backups(backup_root):
    if not os.path.isdir(backup_root):
        print(f"Backup directory {backup_root} does not exist.")
        sys.exit(1)
    backup_folders = validate_and_get_valid_backups(backup_root)
    if not backup_folders:
        print("No backup folders found.")
        sys.exit(1)

    print("\033[36mValidating backup folder structure...\033[0m")
    invalid_backups = []
    for folder in backup_folders:
        # Only validate folder structure, not contents
        manifests_path = os.path.join(folder, "manifests", "registry.ollama.ai", "library")
        blobs_path = os.path.join(folder, "blobs")
        if not os.path.isdir(manifests_path) or not os.path.isdir(blobs_path):
            invalid_backups.append(folder)

    if invalid_backups:
        print("\033[31mInvalid backup folders:\033[0m")
        for invalid_folder in invalid_backups:
            head, tail = os.path.split(invalid_folder)
            if head:
                print(f"  - {head}{os.path.sep}\033[31m{tail}\033[0m")
            else:
                print(f"  - \033[31m{tail}\033[0m")

    print("\033[36mAvailable backup folders:\033[0m")
    for idx, folder in enumerate(sorted(backup_folders)):
        if folder in invalid_backups:
            print(f"[\033[31m{idx:2d}\033[0m] {os.path.basename(folder)}")
        else:
            print(f"[{idx:2d}] {os.path.basename(folder)}")

    return sorted(backup_folders)

def get_backup_selection(backup_folders):
    """Get one or multiple backup selections from user."""
    indices = get_multiple_selections(
        len(backup_folders),
        f"\nSelect backup number(s) (0-{len(backup_folders)-1}): "
    )
    return [backup_folders[i] for i in indices]

def restore_backup(backup_dir, ollama_base):
    if not ollama_base:
        print("Error: Target restore directory not provided")
        sys.exit(1)

    print(f"Restoring backup from {backup_dir} to {ollama_base}...")

    # Restore manifests
    backup_manifests = os.path.join(backup_dir, "manifests")
    target_manifests = os.path.join(ollama_base, "manifests")
    if os.path.isdir(backup_manifests):
        for root, dirs, files in os.walk(backup_manifests):
            rel_path = os.path.relpath(root, backup_manifests)
            dest_dir = os.path.join(target_manifests, rel_path)
            os.makedirs(dest_dir, exist_ok=True)
            for file in files:
                src_file = os.path.join(root, file)
                dest_file = os.path.join(dest_dir, file)
                try:
                    shutil.copy2(src_file, dest_file)
                except Exception as e:
                    print(f"Warning: Failed copying {src_file} to {dest_file}: {str(e)}")
    else:
        print("No manifests directory in backup.")

    # Restore blobs
    backup_blobs = os.path.join(backup_dir, "blobs")
    target_blobs = os.path.join(ollama_base, "blobs")
    if os.path.isdir(backup_blobs):
        os.makedirs(target_blobs, exist_ok=True)
        for file in os.listdir(backup_blobs):
            src_file = os.path.join(backup_blobs, file)
            dest_file = os.path.join(target_blobs, file)
            try:
                shutil.copy2(src_file, dest_file)
            except Exception as e:
                print(f"Warning: Failed copying blob {src_file} to {dest_file}: {str(e)}")
    else:
        print("No blobs directory in backup.")

    print(f"\033[32mSuccessfully restored backup from {backup_dir} to destination directory: {ollama_base}.\033[0m")

def validate_and_get_valid_backups(backup_root):
    """
    Validate and return all valid backup sub-folders inside the given directory.

    Args:
        backup_root (str): The path to the directory containing backup sub-folders.

    Returns:
        list: A list of valid backup sub-folder paths.
    """
    if not os.path.isdir(backup_root):
        raise ValueError(f"The directory '{backup_root}' does not exist.")

    valid_backups = []

    for entry in os.scandir(backup_root):
        if entry.is_dir():
            blobs_dir = os.path.join(entry.path, "blobs")
            manifests_dir = os.path.join(entry.path, "manifests", "registry.ollama.ai", "library")

            if os.path.isdir(blobs_dir) and os.path.isdir(manifests_dir):
                valid_backups.append(entry.path)

    if not valid_backups:
        raise ValueError("No valid backup folders found in the provided directory.")

    return valid_backups

def validate_backup_folder_contents(backup_folder):
    """
    Validate if the blob files in the backup folder exist and optionally check their hashes
    against the manifest file.

    Args:
        backup_folder (str): The path to the backup folder to validate.

    Returns:
        bool: True if validation passes, False otherwise.
    """
    manifests_path = os.path.join(backup_folder, "manifests", "registry.ollama.ai", "library")
    blobs_path = os.path.join(backup_folder, "blobs")

    if not os.path.isdir(manifests_path) or not os.path.isdir(blobs_path):
        print(f"Error: \033[31mMissing\033[0m required directories in {backup_folder}.")
        return False

    for root, _, files in os.walk(manifests_path):
        for manifest_file in files:
            manifest_file_path = os.path.join(root, manifest_file)
            try:
                with open(manifest_file_path, 'r') as f:
                    manifest = json.load(f)
            except Exception as e:
                print(f"Error: Failed to read or parse manifest file {manifest_file_path}: {e}")
                return False

            digests = [manifest['config']['digest']]
            digests.extend(layer['digest'] for layer in manifest['layers'])

            # First check existence of blob files
            print("Checking existence of blob files...")
            missing_blob_found = False
            for digest in digests:
                blob_file_name = digest.replace(':', '-')
                blob_file_path = os.path.join(blobs_path, blob_file_name)
                if not os.path.isfile(blob_file_path):
                    print(f"Error: \033[31mMissing\033[0m blob file {blob_file_name} for digest {digest} in {backup_folder}.")
                    missing_blob_found = True
            
            if missing_blob_found:
                return False

            # Ask user if they want to validate hashes
            while True:
                check_hashes = input("\nWould you like to validate file hashes? This may take some time for large files. (y/n): ").lower()
                if check_hashes in ['y', 'n']:
                    break
                print("Please enter 'y' for yes or 'n' for no.")

            if check_hashes == 'y':
                print("\nValidating integrity of blob files (hash validation)...")
                integrity_error_found = False
                for digest in digests:
                    blob_file_name = digest.replace(':', '-')
                    blob_file_path = os.path.join(blobs_path, blob_file_name)
                    # Validate the hash of the blob file
                    expected_hash = digest.split(':')[1]
                    with open(blob_file_path, 'rb') as blob_file:
                        file_content = blob_file.read()
                        actual_hash = hashlib.sha256(file_content).hexdigest()
                        if actual_hash == expected_hash:
                            print(f"\033[35m{blob_file_name}\033[32m OK\033[0m")
                        else:
                            print(f"\033[31m{blob_file_name}\033[0m \033[31mMismatch\033[0m \033[35m(@{os.path.basename(backup_folder)})\033[0m")
                            print(f"  Expected: {expected_hash}")
                            print(f"  Actual:   {actual_hash}")
                            integrity_error_found = True

                if integrity_error_found:
                    return False
            else:
                print("Skipping hash validation.")

    print(f"\nAll validations completed for {backup_folder}.")
    return True

def backup_mode():
    models = get_ollama_models()
    if not models:
        print("Error: No models found. Please ensure Ollama is running and models are installed.")
        sys.exit(1)
    max_name_length = display_models(models)
    selections = get_user_selection(models)
    
    for selection in selections:
        model_name = models[selection]['Name']
        print(f"\nProcessing: \033[32m{model_name:<{max_name_length}}\033[0m \t"
              f"\033[33m(Size: {models[selection]['Size']})\033[0m")
        backup_model(model_name, max_name_length)
        print("\n" + "="*50 + "\n")

def restore_mode():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Ask user for backup directory path
    while True:
        user_input = input("Enter backup directory path (press Enter to use default ModelBakup): ").strip()
        if user_input.startswith('"') and user_input.endswith('"'):
            user_input = user_input[1:-1]
        backup_root = user_input if user_input else os.path.join(script_dir, "ModelBakup")
        try:
            backup_folders = validate_and_get_valid_backups(backup_root)
            print("Valid backup folders found:")
            for folder in backup_folders:
                print(f"  - {folder}")
            break
        except ValueError as e:
            print(f"Error: {e}")
            print("Please provide a directory with valid backup folders.")

    backup_folders = list_backups(backup_root)
    selected_backups = get_backup_selection(backup_folders)

    # Ask user for restore destination
    default_ollama_path = os.getenv('OLLAMA_MODELS', '')
    while True:
        if default_ollama_path:
            print(f"\nDefault restore path: \033[36m{default_ollama_path}\033[0m")
            user_path = input("Press Enter to use default path or enter a custom path: ").strip()
            if user_path == "":
                if os.path.isdir(default_ollama_path):
                    ollama_base = default_ollama_path
                    break
                else:
                    print(f"\nError: Default path does not exist: {default_ollama_path}")
                    default_ollama_path = ""  # Clear default path to ask for custom path
                    continue
        else:
            print("\nNo default path available (OLLAMA_MODELS environment variable not set)")
            user_path = input("Enter restore path: ").strip()

        if user_path.startswith('"') and user_path.endswith('"'):
            user_path = user_path[1:-1]

        if not user_path and not default_ollama_path:
            print("Error: No path provided. Please enter a valid path.")
            continue

        if not os.path.isdir(user_path):
            create = input("Path does not exist. Create it? (y/n): ").lower()
            if create == 'y':
                try:
                    os.makedirs(user_path)
                    ollama_base = user_path
                    break
                except Exception as e:
                    print(f"Error creating directory: {e}")
                    continue
            continue

        ollama_base = user_path
        break

    print(f"\nSelected restore path: \033[36m{ollama_base}\033[0m")

    # Ask for hash validation once for all backups
    while True:
        check_hashes = input("\nWould you like to validate file hashes for all backups? This may take some time for large files. (y/n): ").lower()
        if check_hashes in ['y', 'n']:
            break
        print("Please enter 'y' for yes or 'n' for no.")

    valid_backups = []
    invalid_backups = []

    for selected_backup in selected_backups:
        print(f"\nProcessing backup: {os.path.basename(selected_backup)}")

        manifests_path = os.path.join(selected_backup, "manifests", "registry.ollama.ai", "library")
        blobs_path = os.path.join(selected_backup, "blobs")

        missing_blob_found = False
        integrity_error_found = False

        for root, _, files in os.walk(manifests_path):
            for manifest_file in files:
                manifest_file_path = os.path.join(root, manifest_file)
                try:
                    with open(manifest_file_path, 'r') as f:
                        manifest = json.load(f)
                except Exception as e:
                    print(f"Error: Failed to read or parse manifest file {manifest_file_path}: {e}")
                    continue

                digests = [manifest['config']['digest']]
                digests.extend(layer['digest'] for layer in manifest['layers'])

                print("\nChecking existence of blob files...")
                for digest in digests:
                    blob_file_name = digest.replace(':', '-')
                    blob_file_path = os.path.join(blobs_path, blob_file_name)
                    if not os.path.isfile(blob_file_path):
                        print(f"Error: \033[31mMissing\033[0m blob file {blob_file_name} for digest {digest}.")
                        missing_blob_found = True

                if check_hashes == 'y' and not missing_blob_found:
                    print("\nValidating integrity of blob files (hash validation)...")
                    for digest in digests:
                        blob_file_name = digest.replace(':', '-')
                        blob_file_path = os.path.join(blobs_path, blob_file_name)
                        expected_hash = digest.split(':')[1]
                        with open(blob_file_path, 'rb') as blob_file:
                            file_content = blob_file.read()
                            actual_hash = hashlib.sha256(file_content).hexdigest()
                            if actual_hash == expected_hash:
                                print(f"\033[35m{blob_file_name}\033[32m OK\033[0m")
                            else:
                                print(f"\033[31m{blob_file_name}\033[0m \033[31mMismatch\033[0m")
                                print(f"  Expected: {expected_hash}")
                                print(f"  Actual:   {actual_hash}")
                                integrity_error_found = True

        if missing_blob_found or integrity_error_found:
            invalid_backups.append(selected_backup)
        else:
            valid_backups.append(selected_backup)

    print("\nProcessing valid backups...")
    for valid_backup in valid_backups:
        print(f"\nRestoring backup: {os.path.basename(valid_backup)}")
        restore_backup(valid_backup, ollama_base)
        print("-" * 50)

    if invalid_backups:
        print("\nThe following backups were skipped due to missing blobs or hash validation errors:")
        for invalid_backup in invalid_backups:
            print(f"  - {os.path.basename(invalid_backup)}")

        while True:
            restore_invalid = input("\nWould you like to attempt restoring skipped backups? (y/n) [default: n]: ").lower()
            if restore_invalid in ['', 'n', 'y']:
                restore_invalid = restore_invalid or 'n'  # Default to 'n' if input is empty
                break
            print("Please enter 'y' for yes or 'n' for no.")

        if restore_invalid == 'y':
            for invalid_backup in invalid_backups:
                print(f"\nRestoring skipped backup: {os.path.basename(invalid_backup)}")
                restore_backup(invalid_backup, ollama_base)
                print("-" * 50)
def main():
    print("\033[36mChoose operation mode:\033[0m")
    print("[1] Backup a model")
    print("[2] Restore a backup")
    choice = input("Enter your choice (1 or 2): ").strip()
    if choice == "1":
        backup_mode()
    elif choice == "2":
        restore_mode()
    else:
        print("Invalid selection. Exiting.")
        sys.exit(1)

if __name__ == "__main__":
    main()
