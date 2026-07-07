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
        final_map[orig_val] = str(row['Replacement'])
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
        # 1. HANDLE INPUT CONVERSION
        working_path = full_path
        if file_name.endswith('.xlsx'):
            sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
            df_temp = pd.read_excel(full_path, sheet_name=sheet)
            working_path = full_path.replace('.xlsx', '_temp_input.csv')
            df_temp.to_csv(working_path, index=False)

        # We write the redacted data to a temporary CSV first
        temp_redacted_csv = os.path.join(DEST_FOLDER, file_name.replace('.xlsx', '_redacted_temp.csv'))
        
        # 2. STREAMING PROCESSING using native CSV module
        with open(working_path, mode='r', encoding='utf-8', newline='') as infile:
            reader = csv.reader(infile)
            header = next(reader)
            
            with open(temp_redacted_csv, mode='w', encoding='utf-8', newline='') as outfile:
                writer = csv.writer(outfile)
                writer.writerow(header)
                
                for row in reader:
                    new_row = []
                    for cell in row:
                        cleaned = clean_value(cell)
                        new_row.append(mapping_dict.get(cleaned, cell))
                    writer.writerow(new_row)

        # 3. FINAL FORMATTING
        final_output_path = os.path.join(DEST_FOLDER, file_name)
        
        if file_name.endswith('.xlsx'):
            # Convert the redacted CSV back to a real Excel file
            df_final = pd.read_csv(temp_redacted_csv)
            df_final.to_excel(final_output_path, index=False)
            os.remove(temp_redacted_csv) # Clean up temp redacted CSV
        else:
            # For CSVs, we just rename the temp redacted file to the final filename
            if os.path.exists(final_output_path): os.remove(final_output_path)
            os.rename(temp_redacted_csv, final_output_path)

        # Cleanup temporary input file
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
    
    master_mapping_df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str})
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    tasks = []
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        mapping_dict = get_redaction_map(file_name, master_mapping_df)
        tasks.append((file_name, full_path, mapping_dict, files_config.get(file_name, {})))

    print(f"Processing {len(tasks)} files in parallel...")
    
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()
