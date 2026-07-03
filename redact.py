import os
import json
import pandas as pd

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

def redact_file(file_path, file_name, master_mapping_df, files_config):
    file_settings = files_config.get(file_name, {})
    
    if file_name.endswith('.csv'):
        df = pd.read_csv(file_path)
    elif file_name.endswith('.xlsx'):
        sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
        df = pd.read_excel(file_path, sheet_name=sheet)
    else:
        return None

    file_rules = master_mapping_df[master_mapping_df['SourceFile'] == file_name]
    if file_rules.empty:
        redacted_path = os.path.join(DEST_FOLDER, file_name)
        if file_name.endswith('.csv'): df.to_csv(redacted_path, index=False)
        else: df.to_excel(redacted_path, index=False)
        return redacted_path

    # Build Type-Aware Map
    final_map = {}
    for _, row in file_rules.iterrows():
        # Clean the key to ensure it matches the lambda cleaning
        orig_val = str(row['Original']).strip()
        if orig_val.endswith('.0'):
            orig_val = orig_val[:-2]
            
        if row['Type'] == 'numeric':
            final_map[orig_val] = float(row['Replacement'])
        else:
            final_map[orig_val] = str(row['Replacement'])

    # Apply Redaction
    for col in file_rules['ColumnName'].unique():
        if col in df.columns:
            def match_and_replace(val):
                if pd.isna(val): return val
                # Convert current cell to a clean string key
                s_val = str(val).strip()
                if s_val.endswith('.0'):
                    s_val = s_val[:-2]
                
                return final_map.get(s_val, val)
            
            df[col] = df[col].apply(match_and_replace)

    redacted_path = os.path.join(DEST_FOLDER, file_name)
    if file_name.endswith('.csv'):
        df.to_csv(redacted_path, index=False)
    else:
        df.to_excel(redacted_path, index=False)
    
    return redacted_path

def main():
    if not os.path.exists(DEST_FOLDER):
        os.makedirs(DEST_FOLDER)

    files_config = load_config()
    if not os.path.exists(LOOKUP_FILE_PATH):
        print(f"Error: {LOOKUP_FILE_PATH} not found!")
        return
    
    master_mapping_df = pd.read_csv(LOOKUP_FILE_PATH)
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        try:
            redact_file(full_path, file_name, master_mapping_df, files_config)
            print(f"Successfully redacted: {file_name}")
        except Exception as e:
            print(f"Error processing {file_name}: {e}")

if __name__ == "__main__":
    main()
