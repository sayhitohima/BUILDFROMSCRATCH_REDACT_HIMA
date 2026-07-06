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
    """Returns targeted columns and a high-speed lookup dictionary"""
    file_rules = master_mapping_df[master_mapping_df['SourceFile'] == file_name]
    target_cols = file_rules['ColumnName'].unique().tolist()
    
    # We build a simple, clean map. 
    # We handle the '.0' and whitespace during the column processing phase.
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
            # FAST READ: Use C engine
            reader = pd.read_csv(full_path, chunksize=CHUNK_SIZE, low_memory=False)
            
            processed_chunks = [] # Store chunks in memory, write once at the end
            
            for chunk in reader:
                # TARGETED REDACTION
                for col in target_cols:
                    if col in chunk.columns:
                        # 1. Cast to string and clean .0 once per column
                        # This is much faster than doing it cell-by-cell
                        cleaned_series = chunk[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                        
                        # 2. .map() is the fastest lookup in Pandas
                        # .fillna() keeps the original value if no match is found in mapping_dict
                        chunk[col] = cleaned_series.map(mapping_dict).fillna(chunk[col])
                
                processed_chunks.append(chunk)
            
            # PERFORMANCE BOOST: Write all chunks at once instead of looping 'mode=a'
            final_df = pd.concat(processed_chunks)
            final_df.to_csv(os.path.join(DEST_FOLDER, file_name), index=False)
                    
        elif file_name.endswith('.xlsx'):
            sheet = file_settings.get('sheet', 0) if isinstance(file_settings, dict) else 0
            df = pd.read_excel(full_path, sheet_name=sheet)
            for col in target_cols:
                if col in df.columns:
                    cleaned = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    df[col] = cleaned.map(mapping_dict).fillna(df[col])
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
    
    master_mapping_df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str})
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    tasks = []
    for file_name in files:
        full_path = os.path.join(SOURCE_FOLDER, file_name)
        redaction_info = get_redaction_data(file_name, master_mapping_df)
        tasks.append((file_name, full_path, redaction_info, files_config.get(file_name, {})))

    print(f"Starting High-Performance Redaction on {len(tasks)} files...")
    
    # ProcessPoolExecutor uses multiple CPU cores
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_single_file, tasks))
    
    for res in results:
        print(res)

if __name__ == "__main__":
    main()
