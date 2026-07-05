import os, json, random, string
import pandas as pd
import numpy as np
from concurrent.futures import ProcessPoolExecutor

# ================= CONFIGURATION =================
SOURCE_FOLDER = "mock_sharepoint/source_files"
CONFIG_FILE = "D:\\himab\\REDACT\\redact_columns.json"
OUTPUT_MAPPING_FILE = "mapping_file.csv"
CHUNK_SIZE = 200000 
# ==================================================


def get_replacement(val, is_numeric, used_set):
    """High-speed replacement generator"""
    s = str(val).strip()
    if is_numeric:
        # Precision-preserved numeric logic
        is_neg = s.startswith('-')
        abs_s = s.lstrip('-')
        before, after = abs_s.split('.') if '.' in abs_s else (abs_s, "")
        
        # Integer math is 10x faster than string joining
        b_len, a_len = len(before), len(after)
        b_val = random.randint(10**(b_len-1), (10**b_len)-1) if b_len > 0 else 0
        a_val = random.randint(0, (10**a_len)-1) if a_len > 0 else 0
        
        res = b_val + (a_val / (10**a_len)) if a_len > 0 else float(b_val)
        if is_neg: res = -res
        
        # Collision check (Rare for 10^len)
        while res == float(s) or res in used_set:
            res += 1.0 # Minimal shift to ensure uniqueness
        used_set.add(res)
        return res, "numeric"
    else:
        # Format-preserved ID logic
        res = "".join(random.choice(string.digits if c.isdigit() else string.ascii_uppercase if c.isalpha() else c) for c in s)
        if res == s: res += "X"
        used_set.add(res)
        return res, "string"

def scan_file(file_info):
    """Parallel worker to find unique values"""
    file_name, file_path, settings = file_info
    cols = settings.get('columns', []) if isinstance(settings, dict) else settings
    uniques = {col: set() for col in cols}
    
    try:
        if file_name.endswith('.csv'):
            # read only needed columns to save RAM
            for chunk in pd.read_csv(file_path, chunksize=CHUNK_SIZE, usecols=cols, low_memory=False):
                for col in cols:
                    uniques[col].update(chunk[col].dropna().astype(str).str.replace(r'\.0$', '', regex=True).str.strip().unique())
        else:
            df = pd.read_excel(file_path, sheet_name=settings.get('sheet', 0) if isinstance(settings, dict) else 0, usecols=cols)
            for col in cols:
                uniques[col].update(df[col].dropna().astype(str).str.replace(r'\.0$', '', regex=True).str.strip().unique())
        return file_name, uniques
    except Exception as e:
        return file_name, None

def generate_mapping():
    config = json.load(open(CONFIG_FILE))
    all_files = [f for f in os.listdir(SOURCE_FOLDER) if f.endswith(('.csv', '.xlsx'))]
    tasks = [(f, os.path.join(SOURCE_FOLDER, f), config[f]) for f in all_files if f in config]
    
    print(f"Scanning {len(tasks)} files in parallel...")
    with ProcessPoolExecutor() as executor:
        results = executor.map(scan_file, tasks)

    final_data = []
    for file_name, uniques in results:
        if uniques is None: continue
        file_ref = os.path.splitext(file_name)[0].replace(" ", "_")
        for col, vals in uniques.items():
            used = set()
            for v in vals:
                # Logic: If it looks like a number, treat as numeric
                is_num = True
                try: float(v)
                except: is_num = False
                
                rep, dtype = get_replacement(v, is_num, used)
                final_data.append([v, rep, file_name, col, dtype])

    pd.DataFrame(final_data, columns=["Original", "Replacement", "SourceFile", "ColumnName", "Type"]).to_csv(OUTPUT_MAPPING_FILE, index=False)
    print(f"Done! Mapping saved to {OUTPUT_MAPPING_FILE}")

if __name__ == "__main__":
    generate_mapping()

