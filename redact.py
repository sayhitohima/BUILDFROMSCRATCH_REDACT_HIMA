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
MAX_WORKERS = 4 
# =======import os


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {}

def create_nested_global_map():
    print("Loading 3.9M mapping records into nested map... please wait.")
    # Use usecols to load only what we need to save RAM during initial load
    df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str, 'Replacement': str, 'SourceFile': str}, low_memory=False)
    
    nested_map = {}
    for row in df.itertuples(index=False):
        file_name = str(row[2]).strip()
        orig = str(row[0]).strip()
        if orig.endswith('.0'): 
            orig = orig[:-2]
        
        if file_name not in nested_map:
            nested_map[file_name] = {}
        
        nested_map[file_name][orig] = str(row[1])
        
    return nested_map

def clean_value(val):
    if val is None: return ""
    s = str(val).strip()
    if s.endswith('.0'):
        return s[:-2]
    return s

def process_single_file(file_info):
    # CHANGE 1: file_specific_map is now passed directly, NOT the global map
    file_name, full_path, file_specific_map, file_settings = file_info
    
    try:
        working_path = full_path
        if file_name.endswith('.xlsx'):
            sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
            df_temp = pd.read_excel(full_path, sheet_name=sheet)
            working_path = full_path.replace('.xlsx', '_temp_input.csv')
            df_temp.to_csv(working_path, index=False)

        temp_redacted_csv = os.path.join(DEST_FOLDER, file_name.replace('.xlsx', '_redacted_temp.csv'))
        
        with open(working_path, mode='r', encoding='utf-8', newline='') as infile:
            reader = csv.reader(infile)
            header = next(reader)
            
            cols_to_redact = file_settings.get('columns', []) if isinstance(file_settings, dict) else file_settings
            target_indices = [i for i, col in enumerate(header) if col in cols_to_redact]
            
            with open(temp_redacted_csv, mode='w', encoding='utf-8', newline='') as outfile:
                writer = csv.writer(outfile)
                writer.writerow(header)
                
                for row in reader:
                    for i in target_indices:
                        cell = row[i]
                        if not cell: continue
                        
                        # The lookup is now against a much smaller, file-specific dictionary
                        if cell in file_specific_map:
                            row[i] = file_specific_map[cell]
                        else:
                            cleaned = clean_value(cell)
                            if cleaned in file_specific_map:
                                row[i] = file_specific_map[cleaned]
                    writer.writerow(row)

        final_output_path = os.path.join(DEST_FOLDER, file_name)
        if file_name.endswith('.xlsx'):
            df_final = pd.read_csv(temp_redacted_csv, low_memory=False)
            df_final.to_excel(final_output_path, index=False)
            os.remove(temp_redacted_csv)
        else:
            if os.path.exists(final_output_path): os.remove(final_output_path)
            os.rename(temp_redacted_csv, final_output_path)

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
    
    global_nested_map = create_nested_global_map()
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    tasks = []
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        
        # CHANGE 2: Extract the specific map for this file RIGHT HERE.
        # Only the slice needed for this file is passed to the ProcessPool.
        file_specific_map = global_nested_map.get(file_name, {})
        
        tasks.append((file_name, full_path, file_specific_map, files_config.get(file_name, {})))

    print(f"Processing {len(tasks)} files using Memory-Optimized Surgical Streaming...")
    
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(process_single_file, tasks))
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()

