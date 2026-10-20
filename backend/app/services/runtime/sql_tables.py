"""Operation and table names from a SQL statement. The statement text is read in memory and never stored."""
import re

OPERATIONS = ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'CALL', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'WITH')
NAME = r'[`"\[]?([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*){0,2})[`"\]]?'
SOURCE = re.compile(r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+' + NAME, re.I)
FROM_LIST = re.compile(r'\bFROM\s+(.*?)(?=\bWHERE\b|\bGROUP\b|\bORDER\b|\bHAVING\b|\bLIMIT\b|\bUNION\b|\bJOIN\b|\)|;|$)', re.I | re.S)
NOT_TABLES = {'select', 'set', 'values', 'where', 'dual', 'lateral', 'only'}
MAX_TABLES = 8
MAX_STATEMENT = 8000


def parse_statement(text: str) -> tuple[str | None, list[str]]:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_STATEMENT:
        return None, []
    text = re.sub(r"'(?:[^']|'')*'", "''", text)             # drop string literals (may hold data)
    text = re.sub(r'/\*.*?\*/|--[^\n]*', ' ', text, flags=re.S)
    first = re.match(r'\s*\(?\s*([A-Za-z]+)', text)
    operation = first.group(1).upper() if first and first.group(1).upper() in OPERATIONS else None
    ctes = {c.lower() for c in re.findall(r'\b([A-Za-z_]\w*)\s+AS\s*\(', text, re.I)} if operation == 'WITH' else set()
    if operation == 'WITH':
        main = re.search(r'\)\s*(SELECT|INSERT|UPDATE|DELETE)\b', text, re.I)
        operation = main.group(1).upper() if main else 'SELECT'
    tables: list[str] = []
    def add(name: str):
        name = name.strip('`"[]')
        if name.lower() not in NOT_TABLES and name.lower() not in ctes and name not in tables and len(tables) < MAX_TABLES:
            tables.append(name)
    for match in SOURCE.finditer(text):
        add(match.group(1))
    for clause in FROM_LIST.findall(text):                    # FROM a, b alias
        for part in clause.split(',')[1:]:
            token = re.match(r'\s*' + NAME, part)
            if token:
                add(token.group(1))
    return operation, tables
