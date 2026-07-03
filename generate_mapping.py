import os
import json
import pandas as pd
import random

# ================= CONFIGURATION =================
SOURCE_FOLDER = "mock_sharepoint/source_files"
CONFIG_FILE = "D:\\himab\\REDACT\\redact_columns.json"
OUTPUT_MAPPING_FILE = "mapping_file.csv"
# ==================================================


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return None

def generate_length_preserved_number(original_val, used_replacements):
    """Generates a number that preserves length and is GUARANTEED to be different from original"""
    s = str(original_val).strip()
    
    # 1. Determine digits before and after decimal
    if '.' in s:
        before, after = s.split('.')
    else:
        before, after = s, ""

    len_before = len(before)
    len_after = len(after)
    original_float = float(s)

    # Keep generating until we find a replacement that is:
    # a) Not already used in this column
    # b) NOT equal to the original value
    while True:
        # Generate random digits for the 'before' part
        first_digit = str(random.randint(1, 9)) if len_before > 0 else "0"
        remaining_before = "".join([str(random.randint(0, 9)) for _ in range(len_before - 1)])
        
        # Generate random digits for the 'after' part
        random_after = "".join([str(random.randint(0, 9)) for _ in range(len_after)])
        
        # Combine them
        if len_after > 0:
            replacement_str = f"{first_digit}{remaining_before}.{random_after}"
        else:
            replacement_str = f"{first_digit}{remaining_before}"
        
        replacement_float = float(replacement_str)
        
        # STRICT CHECK: Must be different from original AND not already used
        if replacement_float != original_float and replacement_float not in used_replacements:
            used_replacements.add(replacement_float)
            return replacement_float

def read_file_generic(file_path, config_val):
    if file_path.endswith('.csv'):
        return pd.read_csv(file_path)
    elif file_path.endswith('.xlsx'):
        sheet = config_val.get('sheet', 0) if isinstance(config_val, dict) else 0
        return pd.read_excel(file_path, sheet_name=sheet)
    return None

def generate_lookup():
    files_config = load_config()
    if not files_config: return

    all_files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    all_mappings = []

    for file_name in all_files:
        if file_name not in files_config:
            continue

        print(f"Processing {file_name}...")
        file_path = os.path.join(SOURCE_FOLDER, file_name)
        file_settings = files_config[file_name]
        df = read_file_generic(file_path, file_settings)
        if df is None: continue
        
        cols_to_redact = file_settings['columns'] if isinstance(file_settings, dict) else file_settings
        file_ref = os.path.splitext(file_name)[0].replace(" ", "_")

        for col in cols_to_redact:
            if col in df.columns:
                is_numeric = pd.api.types.is_numeric_dtype(df[col])
                unique_vals = df[col].dropna().unique()
                
                used_replacements = set()
                
                for val in unique_vals:
                    if is_numeric:
                        # Now guaranteed to be different from 'val'
                        replacement = generate_length_preserved_number(val, used_replacements)
                        dtype = "numeric"
                    else:
                        # For strings, using unique ID based on set length
                        replacement = f"{file_ref}_{col.replace(' ', '')}_{len(used_replacements)}"
                        dtype = "string"
                        used_replacements.add(replacement) # track string replacements too
                    
                    all_mappings.append({
                        "Original": str(val), 
                        "Replacement": replacement, 
                        "SourceFile": file_name,
                        "ColumnName": col,
                        "Type": dtype
                    })
            else:
                print(f"  Warning: Column '{col}' not found in {file_name}")

    mapping_df = pd.DataFrame(all_mappings)
    mapping_df.to_csv(OUTPUT_MAPPING_FILE, index=False)
    print(f"\nSuccess! Guaranteed-different mapping created at: {OUTPUT_MAPPING_FILE}")

if __name__ == "__main__":
    generate_lookup()
