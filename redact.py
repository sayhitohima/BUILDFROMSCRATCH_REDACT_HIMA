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
    return json.load(open(CONFIG_FILE))

def get_file_map(file_name, master_df):
    """Creates a high-speed lookup dictionary for a specific file"""
    rules = master_df[master_df['SourceFile'] == file_name]
    # Pre-clean the keys to match the data cleaning in the loop
    return {str(row.Original).strip().replace('.0', ''): 
            (float(row.Replacement) if row.Type == 'numeric' else str(row.Replacement)) 
            for index, row in rules.iterrows()}

def process_file(file_info):
    file_name, full_path, mapping_dict, settings = file_info
    try:
        if file_name.endswith('.csv'):
            reader = pd.read_csv(full_path, chunksize=CHUNK_SIZE, low_memory=False)
            redacted_path = os.path.join(DEST_FOLDER, file_name)
            first = True
            for chunk in reader:
                # OPTIMIZATION: Only process columns that are actually in our mapping
                # We use .map() instead of .replace() for massive speed gain
                for col in chunk.columns:
                    # Pre-clean only the target columns
                    cleaned_col = chunk[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                    # The .map() function is the fastest way to swap values in Pandas
                    chunk[col] = cleaned_col.map(mapping_dict).fillna(chunk[col])
                
                chunk.to_csv(redacted_path, index=False, mode='w' if first else 'a', header=first)
                first = False
        else:
            sheet = settings.get('sheet', 0) if isinstance(settings, dict) else 0
            df = pd.read_excel(full_path, sheet_name=sheet)
            for col in df.columns:
                cleaned = df[col].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                df[col] = cleaned.map(mapping_dict).fillna(df[col])
            df.to_excel(os.path.join(DEST_FOLDER, file_name), index=False)
            
        return f"Fixed: {file_name}"
    except Exception as e:
        return f"Error {file_name}: {e}"

def main():
    if not os.path.exists(DEST_FOLDER): os.makedirs(DEST_FOLDER)
    config = load_config()
    master_df = pd.read_csv(LOOKUP_FILE_PATH, dtype={'Original': str}, low_memory=False)
    files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    
    tasks = []
    for f in files:
        if f in config:
            tasks.append((f, os.path.join(SOURCE_FOLDER, f), get_file_map(f, master_df), config[f]))

    print(f"Processing {len(tasks)} files in parallel...")
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(process_file, tasks))
    for r in results: print(r)

if __name__ == "__main__":
    main()
