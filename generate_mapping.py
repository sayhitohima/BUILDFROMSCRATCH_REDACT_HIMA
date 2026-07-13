import os, json, random, string
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor

# ================= CONFIGURATION =================
SOURCE_FOLDER = "mock_sharepoint/source_files"
CONFIG_FILE = "D:\\himab\\REDACT\\redact_columns.json"
OUTPUT_MAPPING_FILE = "mapping_file.csv"
OUTPUT_TRUTH_GLOBAL_FILE = "truth_global_mapping.csv" 
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
    """Original high-speed numeric generation preserving length and precision"""
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

def load_truth_tables(config):
    """Loads truth files into memory based on the JSON config"""
    truth_caches = {}
    for file_cfg in config.values():
        if isinstance(file_cfg, dict) and "ref_mapping" in file_cfg:
            for col, ref_info in file_cfg["ref_mapping"].items():
                t_file = ref_info["truth_file"]
                if t_file not in truth_caches:
                    try:
                        path = os.path.join(SOURCE_FOLDER, t_file)
                        df_t = pd.read_excel(path) if t_file.endswith('.xlsx') else pd.read_csv(path)
                        k_col, id_col = ref_info["key_col"], ref_info["id_col"]
                        mapping = {str(row[k_col]).strip().lower(): str(row[id_col]).strip() 
                                   for _, row in df_t.dropna(subset=[k_col, id_col]).iterrows()}
                        truth_caches[t_file] = mapping
                    except Exception as e:
                        print(f"Error loading truth file {t_file}: {e}")
    return truth_caches

def scan_file(file_info):
    file_name, file_path, settings = file_info
    cols = settings.get('columns', []) if isinstance(settings, dict) else settings
    uniques = {col: set() for col in cols}
    try:
        working_path = file_path
        if file_name.endswith('.xlsx'):
            sheet = settings.get('sheet', 0) if isinstance(settings, dict) else 0
            df_temp = pd.read_excel(file_path, sheet_name=sheet)
            working_path = file_path.replace('.xlsx', '_temp_scan.csv')
            df_temp.to_csv(working_path, index=False)
        reader = pd.read_csv(working_path, chunksize=CHUNK_SIZE, usecols=cols, low_memory=False)
        for chunk in reader:
            for col in cols:
                if col in chunk.columns:
                    vals = chunk[col].dropna().astype(str).str.replace(r'\.0$', '', regex=True).str.strip().unique()
                    uniques[col].update(vals)
        if working_path != file_path: 
            os.remove(working_path)
        return file_name, uniques
    except Exception as e:
        print(f"Error scanning {file_name}: {e}")
        return file_name, None

def generate_mapping():
    config = load_config()
    if not config: return
    
    truth_tables = load_truth_tables(config)
    all_files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    tasks = [(f, os.path.join(SOURCE_FOLDER, f), config[f]) for f in all_files if f in config]
    
    print(f"Scanning {len(tasks)} files in parallel...")
    with ProcessPoolExecutor() as executor:
        scan_results = list(executor.map(scan_file, tasks))

    # --- PASS 1: ASSIGN INCREMENTAL INTEGER IDs ---
    field_counters = {}      # { "col": current_max_int }
    anchor_to_int_map = {}   # { ("col", "anchor"): int_id }
    
    temp_final_data = [] 
    temp_truth_data = [] 
    truth_global_seen = set()

    for file_name, uniques in scan_results:
        if uniques is None: continue
        file_settings = config.get(file_name, {})
        ref_mappings = file_settings.get("ref_mapping", {}) if isinstance(file_settings, dict) else {}
        
        for col, vals in uniques.items():
            for v in vals:
                # 1. NUMERIC Logic (Direct Replacement)
                if is_numeric_value(v):
                    temp_final_data.append([v, generate_numeric_rep(v), file_name, col, "numeric"])
                    continue

                # 2. STRING Logic (Incremental ID)
                anchor = v.lower()
                is_truth_match = False
                
                # Check if THIS specific file has a ref_mapping for THIS column
                if col in ref_mappings:
                    ref_info = ref_mappings[col]
                    t_file = ref_info["truth_file"]
                    if t_file in truth_tables and v.lower() in truth_tables[t_file]:
                        anchor = truth_tables[t_file][v.lower()]
                        is_truth_match = True

                # Assign/Retrieve an incremental integer for this (col, anchor)
                key = (col, anchor)
                if key not in anchor_to_int_map:
                    count = field_counters.get(col, 0) + 1
                    field_counters[col] = count
                    anchor_to_int_map[key] = count
                
                int_id = anchor_to_int_map[key]
                temp_final_data.append([v, int_id, file_name, col, "string"])

                if is_truth_match:
                    truth_entry = (v, anchor, int_id, col)
                    if truth_entry not in truth_global_seen:
                        temp_truth_data.append(list(truth_entry))
                        truth_global_seen.add(truth_entry)

    # --- PASS 2: DYNAMIC PADDING BASED ON MAX VALUES ---
    padding_map = {col: len(str(max_val)) for col, max_val in field_counters.items()}

    def format_id(col, val):
        if not isinstance(val, (int, float)): return val 
        p_len = padding_map.get(col, 1)
        return f"{col}_{str(val).zfill(p_len)}"

    final_rows = []
    for row in temp_final_data:
        orig, rep, f_name, col, dtype = row
        if dtype == "string":
            final_rows.append([orig, format_id(col, rep), f_name, col, dtype])
        else:
            final_rows.append(row)

    final_truth_rows = []
    for row in temp_truth_data:
        orig, tid, int_id, col = row
        final_truth_rows.append([orig, tid, format_id(col, int_id), col])

    # Exports
    pd.DataFrame(final_rows, columns=["Original", "Replacement", "SourceFile", "ColumnName", "Type"]).to_csv(OUTPUT_MAPPING_FILE, index=False)
    if final_truth_rows:
        pd.DataFrame(final_truth_rows, columns=["OriginalValue", "TruthID", "GlobalID", "ColumnName"]).to_csv(OUTPUT_TRUTH_GLOBAL_FILE, index=False)

    print(f"Done! High-speed mapping saved to {OUTPUT_MAPPING_FILE}")

if __name__ == "__main__":
    generate_mapping()
