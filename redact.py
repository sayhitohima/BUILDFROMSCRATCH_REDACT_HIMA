import os
import json
import csv
import pandas as pd
from concurrent.futures import ProcessPoolExecutor


# ================= CONFIGURATION =================
SOURCE_FOLDER = "mock_sharepoint/source_files"
DEST_FOLDER = "mock_sharepoint/vendor_export"
LOOKUP_FILE_PATH = "mapping_file.csv"
CONFIG_FILE = "D:\\himab\\REDACT\\redact_columns.json"
# ==================================================


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {}

def get_redaction_map(file_name, master_mapping_df):
    """Creates a flat, high-speed lookup dictionary"""
    file_rules = master_mapping_df[master_mapping_df['SourceFile'] == file_name]
    final_map = {}
    for _, row in file_rules.iterrows():
        orig_val = str(row['Original']).strip()
        if orig_val.endswith('.0'): 
            orig_val = orig_val[:-2]
        
        # Store as is; we will handle type conversion during the write phase
        final_map[orig_val] = row['Replacement']
    return final_map

def clean_value(val):
    """Ultra-fast cleaning of a single cell value"""
    if val is None: return ""
    s = str(val).strip()
    if s.endswith('.0'):
        return s[:-2]
    return s

def process_single_file(file_info):
    file_name, full_path, mapping_dict, file_settings = file_info
    
    try:
        # 1. HANDLE EXCEL CONVERSION (Excel must be converted to CSV to be streamed)
        working_path = full_path
        if file_name.endswith('.xlsx'):
            sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
            df_temp = pd.read_excel(full_path, sheet_name=sheet)
            working_path = full_path.replace('.xlsx', '_temp_main.csv')
            df_temp.to_csv(working_path, index=False)

        redacted_path = os.path.join(DEST_FOLDER, file_name)
        
        # 2. STREAMING PROCESSING using native CSV module (NOT PANDAS)
        with open(working_path, mode='r', encoding='utf-8', newline='') as infile:
            reader = csv.reader(infile)
            header = next(reader) # Read header row
            
            # Find the indices of columns that need redaction to avoid searching by name every row
            # We identify which columns in the CSV match the keys in our mapping
            # Since the mapping is value-based, we apply it to all columns that 
            # might contain values present in the mapping_dict.
            
            with open(redacted_path, mode='w', encoding='utf-8', newline='') as outfile:
                writer = csv.writer(outfile)
                writer.writerow(header) # Write header
                
                for row in reader:
                    # Process every cell in the row
                    # This is the fastest possible way to iterate in Python
                    new_row = []
                    for cell in row:
                        cleaned = clean_value(cell)
                        # Direct hash-map lookup (O(1) complexity)
                        new_row.append(mapping_dict.get(cleaned, cell))
                    writer.writerow(new_row)

        # Cleanup temp file
        if working_path != full_path: os.remove(working_path)
        return f"Successfully redacted: {file_name}"
        
    except Exception as e:
        return f"Error processing {file_name}: {str(e)}"

def main():
    if not os.path.exists(DEST_FOLDER):
        os.makedirs(DEST_FOLDER)

    files_config = load_config()
    if not os.path.exists(LOOKUP_FILE_PATH):
        print(f"Error: {LOOKUP_FILE_PATH} not found!")
        return
    
    # Load mapping file as strings
    master_mapping_df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str}, low_memory=False)
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    tasks = []
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        mapping_dict = get_redaction_map(file_name, master_mapping_df)
        tasks.append((file_name, full_path, mapping_dict, files_config.get(file_name, {})))

    print(f"Processing {len(tasks)} files using Streaming I/O...")
    
    # Process in parallel using CPU cores
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()

