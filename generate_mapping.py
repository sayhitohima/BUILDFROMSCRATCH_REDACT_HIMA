import os, json, random, string
import pandas as pd
from concurrent.futures import ProcessPoolExecutor

# ================= CONFIGURATION =================
SOURCE_FOLDER = "mock_sharepoint/source_files"
CONFIG_FILE = "D:\\himab\\REDACT\\redact_columns.json"
OUTPUT_MAPPING_FILE = "mapping_file.csv"
CHUNK_SIZE = 200000 
# ==================================================


def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return None

def is_numeric_value(val):
    try:
        float(val)
        return True
    except:
        return False

def generate_numeric_rep(val):
    """Fast numeric generation without the while-loop (statistically unique)"""
    s = str(val).strip()
    is_neg = s.startswith('-')
    abs_s = s.lstrip('-')
    before, after = abs_s.split('.') if '.' in abs_s else (abs_s, "")
    b_len, a_len = len(before), len(after)
    
    b_val = str(random.randint(10**(b_len-1), (10**b_len)-1)) if b_len > 0 else "0"
    a_val = "".join(random.choices(string.digits, k=a_len)) if a_len > 0 else ""
    
    res_str = f"{b_val}.{a_val}" if a_len > 0 else b_val
    if is_neg: res_str = "-" + res_str
    return float(res_str)

def generate_string_rep(val):
    """Fast string replacement preserving format"""
    s = str(val).strip()
    return "".join(random.choice(string.digits if c.isdigit() else string.ascii_uppercase if c.isalpha() else c) for c in s)

def scan_file(file_info):
    """Parallel worker to find unique values"""
    file_name, file_path, settings = file_info
    cols = settings.get('columns', []) if isinstance(settings, dict) else settings
    uniques = {col: set() for col in cols}
    
    try:
        # Convert Excel to CSV for chunking efficiency
        working_path = file_path
        if file_name.endswith('.xlsx'):
            from xlsx2csv import Xlsx2Csv
            sheet = settings.get('sheet', 0) if isinstance(settings, dict) else 0
            temp_csv = file_path.replace('.xlsx', '_temp_scan.csv')
            Xlsx2Csv(file_path, temp_csv, options={'sheet': sheet}).convert()
            working_path = temp_csv

        reader = pd.read_csv(working_path, chunksize=CHUNK_SIZE, usecols=cols, low_memory=False)
        for chunk in reader:
            for col in cols:
                if col in chunk.columns:
                    vals = chunk[col].dropna().astype(str).str.replace(r'\.0$', '', regex=True).str.strip().unique()
                    uniques[col].update(vals)
        
        if working_path != file_path: os.remove(working_path)
        return file_name, uniques
    except Exception as e:
        print(f"Error scanning {file_name}: {e}")
        return file_name, None

def generate_mapping():
    config = load_config()
    if not config: return
    all_files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    tasks = [(f, os.path.join(SOURCE_FOLDER, f), config[f]) for f in all_files if f in config]
    
    print(f"Scanning {len(tasks)} files in parallel...")
    with ProcessPoolExecutor() as executor:
        scan_results = list(executor.map(scan_file, tasks))

    # --- STEP 1: AGGREGATE ALL UNIQUES GLOBALLY ---
    global_uniques = set()
    for file_name, uniques in scan_results:
        if uniques:
            for col_set in uniques.values():
                global_uniques.update(col_set)
    
    print(f"Found {len(global_uniques)} unique values globally. Generating replacements...")

    # --- STEP 2: BATCH GENERATE REPLACEMENTS (The Speed-Up) ---
    # We generate the mapping once for every unique value in the entire project
    global_replacement_map = {}
    for val in global_uniques:
        if is_numeric_value(val):
            global_replacement_map[val] = generate_numeric_rep(val)
        else:
            global_replacement_map[val] = generate_string_rep(val)

    # --- STEP 3: MAP BACK TO FILES ---
    final_data = []
    for file_name, uniques in scan_results:
        if uniques is None: continue
        file_ref = os.path.splitext(file_name)[0].replace(" ", "_")
        for col, vals in uniques.items():
            for v in vals:
                rep = global_replacement_map[v]
                dtype = "numeric" if isinstance(rep, float) else "string"
                final_data.append([v, rep, file_name, col, dtype])

    pd.DataFrame(final_data, columns=["Original", "Replacement", "SourceFile", "ColumnName", "Type"]).to_csv(OUTPUT_MAPPING_FILE, index=False)
    print(f"Done! High-speed global mapping saved to {OUTPUT_MAPPING_FILE}")

if __name__ == "__main__":
    generate_mapping()
