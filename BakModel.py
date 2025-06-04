import os
import json
import subprocess
from datetime import datetime
import shutil
import sys
import re
import hashlib

def get_manifest_path(backup_dir, model_name=None):
    """Get the path to the manifest file or directory."""
    base_path = os.path.join(backup_dir, "manifests", "registry.ollama.ai", "library")
    if model_name:
        return os.path.join(base_path, model_name.replace(':', os.path.sep))
    return base_path

def get_blobs_path(backup_dir):
    """Get the path to the blobs directory."""
    return os.path.join(backup_dir, "blobs")

def get_backup_dir(model_name, script_dir=None):
    """Get the backup directory path for a model."""
    if not script_dir:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "ModelBakup", f"{model_name.replace(':', '-')}__{datetime.now().strftime('%Y%m%d_%H%M%S')}")

def get_blob_file_path(blobs_dir, digest):
    """Get the path to a blob file from its digest."""
    return os.path.join(blobs_dir, digest.replace(':', '-'))

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
    """Backup a model to a new directory."""
    ollama_base = os.getenv('OLLAMA_MODELS')
    if not ollama_base:
        print("Error: OLLAMA_MODELS environment variable not set")
        sys.exit(1)

    backup_dir = get_backup_dir(model_name)

    # Handle manifest files
    source_manifest_file = get_manifest_path(ollama_base, model_name)
    manifest_dir = get_manifest_path(backup_dir, model_name.split(':')[0])
    dest_manifest_file = get_manifest_path(backup_dir, model_name)

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

    # Handle blob files
    digests = [manifest['config']['digest']]
    digests.extend(layer['digest'] for layer in manifest['layers'])

    print("Copying blobs...")
    blobs_dir = get_blobs_path(backup_dir)
    os.makedirs(blobs_dir, exist_ok=True)
    for digest in digests:
        source_file = get_blob_file_path(get_blobs_path(ollama_base), digest)
        dest_file = get_blob_file_path(blobs_dir, digest)
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

def calculate_backup_statistics(backup_folders):
    """Calculate and return statistics about backup folders."""
    total_backups = len(backup_folders)
    total_blobs = sum(len(os.listdir(os.path.join(folder, "blobs"))) for folder in backup_folders)
    total_size = sum(
        sum(os.path.getsize(os.path.join(folder, "blobs", blob)) for blob in os.listdir(os.path.join(folder, "blobs")))
        for folder in backup_folders
    )
    return total_backups, total_blobs, total_size

def get_model_info_from_manifest(manifests_path):
    """Extract model name and parameters from manifest directory."""
    parameters = "Unknown"
    model_name = "Unknown"
    for root, dirs, files in os.walk(manifests_path):
        if "library" in root:
            if dirs:
                model_name = dirs[0]
                model_folder_path = os.path.join(root, model_name)
                model_files = os.listdir(model_folder_path)
                if model_files:
                    parameters = model_files[0]
            break
    return model_name, parameters

def analyze_backup_folder(folder):
    """Analyze a single backup folder and return its details."""
    manifests_path = os.path.join(folder, "manifests", "registry.ollama.ai", "library")
    blobs_path = os.path.join(folder, "blobs")
    structure_OK = os.path.isdir(manifests_path) and os.path.isdir(blobs_path)

    folder_name = os.path.basename(folder)
    total_size = sum(
        os.path.getsize(os.path.join(folder, "blobs", blob))
        for blob in os.listdir(os.path.join(folder, "blobs"))
    )
    total_size_mb = total_size / (1024 ** 2)

    model_name, parameters = ("Unknown", "Unknown")
    have_missing_blob = False

    if structure_OK:
        model_name, parameters = get_model_info_from_manifest(manifests_path)
        
        # Check for missing blobs by examining manifest files
        for root, _, files in os.walk(manifests_path):
            for manifest_file in files:
                manifest_file_path = os.path.join(root, manifest_file)
                try:
                    with open(manifest_file_path, 'r') as f:
                        manifest = json.load(f)
                    # Get all required digests from manifest
                    digests = [manifest['config']['digest']]
                    digests.extend(layer['digest'] for layer in manifest['layers'])
                    
                    # Check each blob file
                    for digest in digests:
                        blob_file_name = digest.replace(':', '-')
                        blob_file_path = os.path.join(blobs_path, blob_file_name)
                        if not os.path.isfile(blob_file_path):
                            have_missing_blob = True
                            break
                    if have_missing_blob:
                        break
                except Exception:
                    have_missing_blob = True
                    break

    return {
        "name": model_name,
        "size_mb": total_size_mb,
        "parameters": parameters,
        "folder": folder,
        "folder_name": folder_name,
        "structure_OK": structure_OK,
        "have_missing_blob": have_missing_blob,
        "is_problematic": not structure_OK or have_missing_blob
    }

def display_backup_statistics(total_backups, total_blobs, total_size):
    """Display backup statistics in a formatted way."""
    print("\nCalculating backup statistics...")
    print(f"\nTotal backups available: \033[36m{total_backups}\033[0m")
    print(f"Total blob files across all backups: \033[36m{total_blobs}\033[0m")
    print(f"Total size of all backups: \033[36m{total_size / (1024 ** 2):.2f} MB\033[0m")

def display_backup_list(backup_details):
    """Display the list of backups in a formatted table."""
    print("\nAvailable backups:")
    # print(f"{'Index':<6} {'Model Name':<20} {'Size (MB)':<10} {'Params':<20} {'Structure':<10} {'Folder':<33}")
    print(f"{'Index':<6} {'Model Name':<24} {'Size (MB)':<10} {'Params':<15} {'Folder':<33}")
    print("-" * 105)

    for idx, backup in enumerate(backup_details):
        # Determine structure status icon
        if not backup['structure_OK']:
            structure_icon = "\033[31m✗\033[0m"  # Red cross for invalid structure
        elif backup['have_missing_blob']:
            structure_icon = "\033[33m⚠\033[0m"  # Yellow warning for missing blobs
        else:
            structure_icon = "\033[32m✔\033[0m"  # Green check for OK

        # Truncate folder name if too long
        folder_name = backup['folder_name']
        if len(folder_name) > 33:
            folder_name = f"{folder_name[:15]}...{folder_name[-15:]}"

        print(f"[{idx:<4}] {backup['name']:<24} {backup['size_mb']:<10.2f} "
              f"{backup['parameters']:<15} {structure_icon:<11} {folder_name:<33}")

def list_backups(backup_root):
    """List and validate all backups in the given directory."""
    if not os.path.isdir(backup_root):
        print(f"Backup directory {backup_root} does not exist.")
        sys.exit(1)
    backup_folders = validate_and_get_valid_backups(backup_root)
    if not backup_folders:
        print("No backup folders found.")
        sys.exit(1)

    # Calculate statistics
    total_backups, total_blobs, total_size = calculate_backup_statistics(backup_folders)
    display_backup_statistics(total_backups, total_blobs, total_size)

    print("\033[36mValidating backup folder structure...\033[0m")
    invalid_backups = []
    backup_details = []

    # Analyze each backup folder
    for folder in backup_folders:
        details = analyze_backup_folder(folder)
        backup_details.append(details)
        if not details['structure_OK']:
            invalid_backups.append(folder)

    # Sort backups by size
    backup_details.sort(key=lambda x: x['size_mb'], reverse=True)

    # Display results
    display_backup_list(backup_details)

    if invalid_backups:
        print("\n\033[33mNote: Invalid backups are marked in red and may be incomplete or corrupted.\033[0m")

    print("\nNote: Only structure is checked; hashes are not validated yet.")

    return [b['folder'] for b in backup_details]

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

def validate_backup_folder_contents(backup_folder, validate_hashes=False):
    """
    Validate if the blob files in the backup folder exist and optionally check their hashes
    against the manifest file.

    Args:
        backup_folder (str): The path to the backup folder to validate.
        validate_hashes (bool): Whether to validate file hashes.

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

            # Check hashes if validation is requested
            if validate_hashes:
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
    """Restore models from backup folders."""
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

            # Display problematic folders
            invalid_folders = [folder for folder in backup_folders if analyze_backup_folder(folder)['is_problematic']]
            if invalid_folders:
                print("\nProblematic folders detected:")
                for folder in invalid_folders:
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
        is_valid = validate_backup_folder_contents(selected_backup, check_hashes == 'y')
        if is_valid:
            valid_backups.append(selected_backup)
        else:
            invalid_backups.append(selected_backup)

    # Process valid backups
    print("\nProcessing valid backups...")
    for valid_backup in valid_backups:
        print(f"\nRestoring backup: {os.path.basename(valid_backup)}")
        restore_backup(valid_backup, ollama_base)
        print("-" * 50)

    # Handle invalid backups
    if invalid_backups:
        print("\nThe following backups were skipped due to validation errors:")
        for invalid_backup in invalid_backups:
            print(f"  - {os.path.basename(invalid_backup)}")

        # Ask about restoring invalid backups
        while True:
            restore_invalid = input("\nWould you like to attempt restoring invalid backups? (y/n) [default: n]: ").lower()
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
