import os

def load_glossary(file_path: str) -> dict:
    # csv
    glossary = {}
    if not os.path.exists(file_path):
        return glossary
    
    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:
                continue  # skip header
            parts = line.strip().split(",")
            if len(parts) != 2:
                continue  # skip malformed lines
            src_term, tgt_term = parts
            glossary[src_term.strip()] = tgt_term.strip()
    
    return glossary