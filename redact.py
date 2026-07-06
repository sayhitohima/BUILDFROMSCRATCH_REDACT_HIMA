import os, json
import pandas as pd
from concurrent.futures import ProcessPoolExecutor


# ================= CONFIGURATION =================
SOURCE_FOLDER = "mock_sharepoint/source_files"
DEST_FOLDER = "mock_sharepoint/vendor_export"
LOOKUP_FILE_PATH = "mapping_file.csv"
CONFIG_FILE = "D:\\himab\\REDACT\\redact_columns.json"
CHUNK_SIZE = 200000 # Increased chunk size for better throughput
# ==================================================


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        return {}

def get_redaction_data(file_name, master_mapping_df):
    """
    Returns two things:
    1. The list of columns that actually need to be touched.
    2. The mapping dictionary for those values.
    """
    file_rules = master_mapping_df[master_mapping_df['SourceFile'] == file_name]
    
    # Get ONLY the columns that have mappings for this file
    target_cols = file_rules['ColumnName'].unique().tolist()
    
    final_map = {}
    for _, row in file_rules.iterrows():
        orig_val = str(row['Original']).strip()
        if orig_val.endswith('.0'): 
            orig_val = orig_val[:-2]
        
        final_map[orig_val] = float(row['Replacement']) if row['Type'] == 'numeric' else str(row['Replacement'])
        
    return target_cols, final_map

def process_single_file(file_info):
    file_name, full_path, redaction_info, file_settings = file_info
    target_cols, mapping_dict = redaction_info
    
    try:
        if file_name.endswith('.csv'):
            # Use standard C engine with chunking
            reader = pd.read_csv(full_path, chunksize=CHUNK_SIZE, low_memory=False)
            redacted_path = os.path.join(DEST_FOLDER, file_name)
            
            first_chunk = True
            for chunk in reader:
                # PERFORMANCE BOOST: Only loop through columns that need redaction
                # This skips 90% of the work for most files
                for col in target_cols:
                    if col in chunk.columns:
                        # Step 1: Clean the column to match the mapping keys
                        # We only do this for the targeted column
                        chunk[col] = chunk[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                        
                        # Step 2: Vectorized mapping (the fastest possible way in Pandas)
                        chunk[col] = chunk[col].map(mapping_dict).fillna(chunk[col])
                
                if first_chunk:
                    chunk.to_csv(redacted_path, index=False, mode='w')
                    first_chunk = False
                else:
                    chunk.to_csv(redacted_path, index=False, mode='a', header=False)
                    
        elif file_name.endswith('.xlsx'):
            sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
            df = pd.read_excel(full_path, sheet_name=sheet)
            
            # TARGETED REDACTION for Excel
            for col in target_cols:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    df[col] = df[col].map(mapping_dict).fillna(df[col])
            
            df.to_excel(os.path.join(DEST_FOLDER, file_name), index=False)
            
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
    
    # Force Original to string to avoid mixed-type warnings
    master_mapping_df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str})
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    tasks = []
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        # Pre-calculate the targeted columns and the map
        redaction_info = get_redaction_data(file_name, master_mapping_df)
        tasks.append((file_name, full_path, redaction_info, files_config.get(file_name, {})))

    print(f"Executing Surgical Redaction on {len(tasks)} files...")
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()
