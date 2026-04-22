import os

def load_glossary(file_path: str) -> dict:
    glossary = {}
    if not os.path.exists(file_path):
        return glossary

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:
                continue
            parts = line.strip().split(",")
            if len(parts) != 2:
                continue
            src_term, tgt_term = parts
            glossary[src_term.strip()] = tgt_term.strip()

    return glossary


def load_honorifics(file_path: str) -> list:
    honorifics = []
    if not os.path.exists(file_path):
        return honorifics

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:
                continue
            parts = line.strip().split(",")
            if len(parts) != 3:
                continue
            caller, target, honorific = [p.strip() for p in parts]
            honorifics.append((caller, target, honorific))

    return honorifics