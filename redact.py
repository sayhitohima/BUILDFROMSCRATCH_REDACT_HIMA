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
# Set this based on your RAM (4 for 16GB, 8 for 32GB)
MAX_WORKERS = 4 
# ==================================================

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {}

def create_global_map():
    """Loads the massive mapping file into a single high-speed dictionary"""
    print("Loading mapping records into memory... please wait.")
    # Force everything to string to prevent DtypeWarnings and precision loss
    df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str, 'Replacement': str})
    
    global_map = {}
    for row in df.itertuples(index=False):
        orig = str(row[0]).strip()
        if orig.endswith('.0'): 
            orig = orig[:-2]
        global_map[orig] = str(row[1])
    return global_map

def clean_value(val):
    """Ultra-fast cleaning for hash-map lookup"""
    if val is None: return ""
    s = str(val).strip()
    if s.endswith('.0'):
        return s[:-2]
    return s

def process_single_file(file_info):
    file_name, full_path, global_map, file_settings = file_info
    
    try:
        # --- STEP 1: CONVERT XLSX TO TEMP CSV ---
        # We do this because pandas.read_excel loads the whole file into RAM.
        # Once it is a CSV, we can stream it row-by-row.
        working_path = full_path
        if file_name.endswith('.xlsx'):
            sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
            df_temp = pd.read_excel(full_path, sheet_name=sheet)
            # Use a unique temp name to avoid collisions during parallel processing
            working_path = os.path.join(DEST_FOLDER, f"temp_in_{file_name}.csv")
            df_temp.to_csv(working_path, index=False)

        # Temp file for the redacted version before converting back to XLSX
        temp_redacted_csv = os.path.join(DEST_FOLDER, f"temp_red_{file_name}.csv")
        
        # --- STEP 2: STREAMING REDACTION (The high-speed part) ---
        with open(working_path, mode='r', encoding='utf-8', newline='') as infile:
            reader = csv.reader(infile)
            header = next(reader)
            
            cols_to_redact = file_settings.get('columns', []) if isinstance(file_settings, dict) else file_settings
            target_indices = [i for i, col in enumerate(header) if col in cols_to_redact]
            
            with open(temp_redacted_csv, mode='w', encoding='utf-8', newline='') as outfile:
                writer = csv.writer(outfile)
                writer.writerow(header)
                
                for row in reader:
                    # Surgical Redaction: Only touch target columns
                    for i in target_indices:
                        cell = row[i]
                        if not cell: continue
                        
                        # Fast Path: Direct lookup
                        if cell in global_map:
                            row[i] = global_map[cell]
                        else:
                            # Slow Path: Clean then lookup
                            cleaned = clean_value(cell)
                            if cleaned in global_map:
                                row[i] = global_map[cleaned]
                    writer.writerow(row)

        # --- STEP 3: FINAL FORMATTING ---
        final_output_path = os.path.join(DEST_FOLDER, file_name)
        
        if file_name.endswith('.xlsx'):
            # Read the redacted CSV and save as a proper binary .xlsx file
            df_final = pd.read_csv(temp_redacted_csv)
            df_final.to_excel(final_output_path, index=False)
            os.remove(temp_redacted_csv)
        else:
            if os.path.exists(final_output_path): os.remove(final_output_path)
            os.rename(temp_redacted_csv, final_output_path)

        # Final cleanup of the temporary input CSV
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
    
    # Load the 3.9M records once
    global_mapping_dict = create_global_map()
    
    # Only look for .xlsx and .csv
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    tasks = []
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        tasks.append((file_name, full_path, global_mapping_dict, files_config.get(file_name, {})))

    print(f"Processing {len(tasks)} files using Surgical Streaming...")
    
    # Process in parallel to utilize all CPU cores
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(process_single_file, tasks))
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()
