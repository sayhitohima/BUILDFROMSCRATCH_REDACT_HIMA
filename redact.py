import os
import json
import pandas as pd
from concurrent.futures import ProcessPoolExecutor # For Parallel Processing

# ================= CONFIGURATION =================
SOURCE_FOLDER = "mock_sharepoint/source_files"
DEST_FOLDER = "mock_sharepoint/vendor_export"
LOOKUP_FILE_PATH = "mapping_file.csv"
CONFIG_FILE = "D:\\himab\\REDACT\\redact_columns.json"
CHUNK_SIZE = 100000 # Increased chunk size for better throughput
# ==================================================


def load_config():
    """Loads the JSON configuration file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def get_redaction_map(file_name, master_mapping_df):
    """
    Creates a dictionary for a specific file: 
    { 'OriginalValue': ReplacementValue }
    """
    # Filter master mapping for only the rules that apply to this specific file
    file_rules = master_mapping_df[master_mapping_df['SourceFile'] == file_name]
    
    final_map = {}
    for _, row in file_rules.iterrows():
        # Clean the key to ensure it matches the cleaning logic in the loop
        orig_val = str(row['Original']).strip()
        if orig_val.endswith('.0'): 
            orig_val = orig_val[:-2]
        
        # Store replacement as float if numeric, otherwise string
        if row['Type'] == 'numeric':
            final_map[orig_val] = float(row['Replacement'])
        else:
            final_map[orig_val] = str(row['Replacement'])
    return final_map

def process_single_file(file_info):
    """
    Worker function to process one file. 
    This is executed in parallel across CPU cores.
    """
    file_name, full_path, mapping_dict, file_settings = file_info
    
    try:
        # ------------------- CSV PROCESSING -------------------
        if file_name.endswith('.csv'):
            # Read in chunks for memory efficiency
            reader = pd.read_csv(full_path, chunksize=CHUNK_SIZE, low_memory=False)
            redacted_path = os.path.join(DEST_FOLDER, file_name)
            
            first_chunk = True
            for chunk in reader:
                # CRITICAL FIX: We ONLY apply .str to the column (Series), not the DataFrame
                for col in chunk.columns:
                    # Only clean and replace if the value is actually in our mapping
                    # This is a performance optimization
                    chunk[col] = chunk[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                
                # Perform the vectorized replacement across the whole chunk
                chunk = chunk.replace(mapping_dict)
                
                # Write chunk to file
                if first_chunk:
                    chunk.to_csv(redacted_path, index=False, mode='w')
                    first_chunk = False
                else:
                    chunk.to_csv(redacted_path, index=False, mode='a', header=False)
                    
        # ------------------- EXCEL PROCESSING -------------------
        elif file_name.endswith('.xlsx'):
            # Handle sheet specification from config
            sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
            df = pd.read_excel(full_path, sheet_name=sheet)
            
            # CRITICAL FIX: Process each column individually to avoid 'DataFrame' object has no attribute 'str'
            for col in df.columns:
                df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            
            # Vectorized replacement
            df = df.replace(mapping_dict)
            
            df.to_excel(os.path.join(DEST_FOLDER, file_name), index=False)
            
        return f"Successfully redacted: {file_name}"
    
    except Exception as e:
        return f"Error processing {file_name}: {str(e)}"

def main():
    # Ensure output directory exists
    if not os.path.exists(DEST_FOLDER):
        os.makedirs(DEST_FOLDER)

    # Load configuration and mapping keys
    files_config = load_config()
    if not os.path.exists(LOOKUP_FILE_PATH):
        print(f"Error: {LOOKUP_FILE_PATH} not found! Please run generate_mapping.py first.")
        return
    
    # Read mapping file; force Original to string to prevent mixed-type warnings
    master_mapping_df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str})
    
    # Get list of all target files
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    # Prepare the list of tasks (tuple of arguments) for the parallel executor
    tasks = []
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        # Generate the mapping dictionary for this specific file
        mapping_dict = get_redaction_map(file_name, master_mapping_df)
        # Get the specific settings (sheet name, etc.) from config.json
        file_settings = files_config.get(file_name, {})
        
        tasks.append((file_name, full_path, mapping_dict, file_settings))

    print(f"Starting parallel processing of {len(files)} files...")
    
    # Execute the tasks in parallel using all available CPU cores
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))
    
    # Print the outcome of each file
    for res in results:
        print(res)

if __name__ == "__main__":
    main()
