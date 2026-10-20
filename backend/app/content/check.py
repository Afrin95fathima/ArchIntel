"""Content check: banned phrases and prose sentences that name nothing and count nothing.

Run `python scripts/check_content.py` or let `tests/test_content_rules.py` run it; both fail on any violation that is
not in the `allow` list of content-rules.yaml.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = Path(__file__).with_name('content-rules.yaml')
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(\[])')
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
NOT_NAMES = {'e.g', 'i.e', 'etc', 'vs', 'a.k.a'}
CODE_TOKENS = [
    re.compile(r'\b[a-z]+[A-Z][A-Za-z0-9]*\b'),             # camelCase
    re.compile(r'\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b'),      # CamelCase
    re.compile(r'\b[A-Za-z0-9]+_[A-Za-z0-9_]+\b'),           # snake_case, UPPER_SNAKE
    re.compile(r'\b[A-Za-z][\w-]*\.[A-Za-z][A-Za-z0-9_]+\b'),   # file, package or attribute names: debt-rules.yaml, javax.persistence, code.namespace
    re.compile(r'`[^`]+`'),
    re.compile(r'[/@#][A-Za-z][\w/.-]+'),                    # routes, annotations, anchors
    re.compile(r'\b[A-Z]{2,}[A-Z0-9]*\b'),                   # acronyms: JAR, HTTP, JPA
]
PLACEHOLDER = re.compile(r'\{[^{}]*\}|\$\{|%[sdr]|<[a-z]+ ?/>')


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    kind: str          # BANNED or NO_SPECIFIC
    detail: str
    text: str

    def render(self):
        return f'{self.file}:{self.line}: {self.kind} {self.detail}: {self.text}'


@lru_cache(maxsize=2)
def load_rules(path: Path = RULES_PATH) -> dict:
    rules = yaml.safe_load(path.read_text(encoding='utf-8'))
    rules['_banned'] = [re.compile(r'(?<![\w-])(?:' + p + r')(?![\w-])', re.I) for p in rules['banned_phrases']]
    rules['_products'] = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(t) for t in rules['product_terms']) + r')(?!\w)')
    return rules


def is_specific(sentence: str, rules: dict, dynamic: bool = False) -> bool:
    if dynamic or PLACEHOLDER.search(sentence) or re.search(r'\d', sentence):
        return True
    lowered = sentence.lower()
    if rules['_products'].search(sentence) or any(m in sentence for m in rules['definition_markers']) or any(m in lowered for m in rules['data_markers']):
        return True
    # a capitalised word that does not open the sentence names a product area, screen, standard or proper noun
    words = WORD.findall(sentence)
    if any(w[0].isupper() and len(w) > 1 and w.lower() not in ('i',) for w in words[1:]):
        return True
    for pattern in CODE_TOKENS:
        for match in pattern.finditer(sentence):
            if match.group(0).strip('.').lower() not in NOT_NAMES and not match.group(0).lower().endswith(('.', 'e.g', 'i.e')):
                return True
    return False


def sentences(text: str) -> list[str]:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return [s for s in SENTENCE_SPLIT.split(text) if s]


def check_text(text: str, file: str, line: int, rules: dict, dynamic: bool = False, role: str = 'prose') -> list[Violation]:
    found = []
    for sentence in sentences(text):
        question = sentence.rstrip().endswith('?')        # a question or an example prompt makes no claim
        for pattern in rules['_banned']:
            match = pattern.search(sentence)
            if match:
                found.append(Violation(file, line, 'BANNED', f'"{match.group(0)}"', sentence[:200]))
        words = WORD.findall(sentence)
        if role == 'prose' and not question and len(words) >= rules['min_words'] and words[0] not in rules['imperative_starts'] and not is_specific(sentence, rules, dynamic):
            found.append(Violation(file, line, 'NO_SPECIFIC', 'names nothing and counts nothing', sentence[:200]))
    return found


# ---------------------------------------------------------------- extraction

def prose_like(text: str) -> bool:
    """Skip identifiers, SQL, regular expressions, paths and other non-prose strings."""
    if ' ' not in text.strip() or len(text) < 20 or re.search(r'\\[bBwWsSdD]|\(\?|\|', text):       # regular expressions are not prose
        return False
    letters = sum(c.isalpha() or c == ' ' for c in text)
    if letters / len(text) < .7:
        return False
    return not re.match(r'^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|WITH|/|\^|http|import |from |def |class )', text.strip())


MESSAGE_CALLS: set[str] = set()


def python_strings(path: Path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, 'value', None), ast.Constant) and isinstance(first.value.value, str):
                skip.add(id(first.value))
        if isinstance(node, ast.Dict):
            skip.update(id(k) for k in node.keys if k is not None)
        if isinstance(node, ast.Subscript):
            skip.add(id(node.slice))
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') in ('get', 'pop', 'setdefault', 'getenv', 'execute', 'text', 'startswith', 'endswith', 'join', 'split', 'replace'):
            skip.update(id(a) for a in node.args if isinstance(a, ast.Constant))
        if isinstance(node, ast.Compare):
            skip.update(id(c) for c in [node.left] + node.comparators if isinstance(c, ast.Constant))
    messages, dynamic_parts = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):       # "text" + value + "more text" is one sentence carrying data
            leaves, stack = [], [node]
            while stack:
                n = stack.pop()
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                    stack.extend([n.left, n.right])
                else:
                    leaves.append(n)
            if any(not (isinstance(n, ast.Constant) and isinstance(n.value, str)) for n in leaves):
                dynamic_parts.update(id(n) for n in leaves if isinstance(n, ast.Constant))
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', '')
            if name in MESSAGE_CALLS or name.endswith(('Error', 'Exception')):
                for arg in list(node.args) + [k.value for k in node.keywords if k.arg in ('detail', 'message')]:
                    messages.update(id(n) for n in ast.walk(arg))
        if isinstance(node, ast.Assign):          # reason = '...' and outcome, reason = 'ALLOW', '...'
            for target in node.targets:
                pairs = list(zip(target.elts, node.value.elts)) if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple) and len(target.elts) == len(node.value.elts) else [(target, node.value)]
                for t, v in pairs:
                    if isinstance(t, ast.Name) and re.search(r'(^|_)(reason|message|detail|error|remediation|impact)$', t.id):
                        messages.update(id(n) for n in ast.walk(v))
        if isinstance(node, ast.keyword) and node.arg and re.search(r'(^|_)(reason|message|detail|error|remediation|impact)$', node.arg):
            messages.update(id(n) for n in ast.walk(node.value))     # status and diagnostic fields are system messages, not content
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and re.search(r'(^|_)(reason|message|detail|error|remediation|impact)$', k.value):
                    messages.update(id(n) for n in ast.walk(v))
    for node in ast.walk(tree):
        role = 'message' if id(node) in messages else 'prose'
        if isinstance(node, ast.JoinedStr):
            static = ' '.join(v.value for v in node.values if isinstance(v, ast.Constant))
            for v in node.values:
                skip.add(id(v))
            yield node.lineno, static, True, role
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value, id(node) in dynamic_parts, role


def blank_code(source: str) -> tuple[str, list[tuple[int, str, bool, str]]]:
    """Return the source with strings and comments replaced by spaces (newlines kept), and the strings found as (line, text, dynamic)."""
    out, strings, i, line = [], [], 0, 1
    n = len(source)
    while i < n:
        c = source[i]
        if c == '\n':
            out.append(c); line += 1; i += 1
        elif source.startswith('//', i):
            j = source.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i)); i = j
        elif source.startswith('/*', i):
            j = source.find('*/', i + 2)
            j = n if j < 0 else j + 2
            block = source[i:j]
            out.append(re.sub(r'[^\n]', ' ', block)); line += block.count('\n'); i = j
        elif c in '\'"':
            j = i + 1
            while j < n and source[j] != c and source[j] != '\n':
                j += 2 if source[j] == '\\' else 1
            role = 'message' if re.search(r'Error\(\s*$', source[max(0, i - 24):i]) else 'prose'
            strings.append((line, source[i + 1:j], False, role))
            out.append(' ' * (j + 1 - i)); i = j + 1
        elif c == '`':
            j, depth, dynamic = i + 1, 0, False
            while j < n and not (source[j] == '`' and depth == 0):
                if source.startswith('${', j):
                    depth += 1; dynamic = True; j += 2; continue
                if source[j] == '}' and depth:
                    depth -= 1
                if source[j] == '\\':
                    j += 1
                j += 1
            body = source[i + 1:j]
            strings.append((line, re.sub(r'\$\{[^}]*\}', ' ', body), dynamic, 'message' if re.search(r'Error\(\s*$', source[max(0, i - 24):i]) else 'prose'))
            out.append(re.sub(r'[^\n]', ' ', source[i:j + 1])); line += body.count('\n'); i = j + 1
        else:
            out.append(c); i += 1
    return ''.join(out), strings


def tsx_strings(path: Path):
    source = path.read_text(encoding='utf-8')
    blanked, strings = blank_code(source)
    for line, text, dynamic, role in strings:
        yield line, text, dynamic, role
    # JSX text: runs between a tag end and the next tag or expression, in the source with strings and comments removed
    for match in re.finditer(r'(?<![=\-])>([^<>{}=;&|]{12,}?)(?=[<{])', blanked):
        text = match.group(1)
        if len(WORD.findall(text)) < 2:
            continue
        before = blanked[match.start() - 1:match.start()]
        dynamic = blanked[match.end():match.end() + 1] == '{' or blanked[match.start() - 1:match.start()] == '}'
        yield blanked.count('\n', 0, match.start(1)) + 1, re.sub(r'\s+', ' ', text), dynamic, 'prose'


def yaml_strings(path: Path):
    node = yaml.compose(path.read_text(encoding='utf-8'))
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, yaml.ScalarNode):
            if n.tag == 'tag:yaml.org,2002:str':
                yield n.start_mark.line + 1, n.value, False, 'prose'
        elif isinstance(n, yaml.MappingNode):
            stack.extend(v for _, v in n.value)
        elif isinstance(n, yaml.SequenceNode):
            stack.extend(n.value)


def markdown_prose(path: Path):
    in_code = False
    paragraph, start = [], 0
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        stripped = raw.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(('#', '|', '>', '<!--')) or re.fullmatch(r'[-*_ ]*', stripped) or re.match(r'^\|?[- :|]+$', stripped):
            if paragraph:
                yield start, ' '.join(paragraph), False, 'prose'
                paragraph = []
            continue
        if not stripped:
            if paragraph:
                yield start, ' '.join(paragraph), False, 'prose'
                paragraph = []
            continue
        text = re.sub(r'^([-*+]|\d+[.)])\s+', '', stripped)
        text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
        if not paragraph:
            start = number
        paragraph.append(text)
    if paragraph:
        yield start, ' '.join(paragraph), False, 'prose'


def files(rules: dict, root: Path):
    skip = rules['scan']['skip_names']
    def keep(p: Path):
        return not any(s in str(p.relative_to(root)) for s in skip)
    for base in rules['scan']['frontend']:
        for p in sorted((root / base).rglob('*.tsx')):
            if keep(p):
                yield p, tsx_strings
    for base in rules['scan']['backend']:
        for p in sorted((root / base).rglob('*.py')):
            if keep(p):
                yield p, python_strings
    for base in rules['scan']['rule_files']:
        for p in sorted((root / base).rglob('*.yaml')):
            yield p, yaml_strings
    for name in rules['scan']['docs']:
        p = root / name
        if p.exists():
            yield p, markdown_prose


def scan(root: Path = ROOT, rules: dict | None = None) -> list[Violation]:
    rules = rules or load_rules()
    MESSAGE_CALLS.clear(); MESSAGE_CALLS.update(rules.get('message_calls', []))
    found = []
    for path, extract in files(rules, root):
        relative = str(path.relative_to(root))
        role_default = 'definition' if relative in rules.get('definition_files', []) or relative in rules.get('prompt_files', []) else 'message' if relative in rules.get('message_files', []) or relative in rules.get('product_help_files', []) else 'prose'
        for line, text, dynamic, role in extract(path):
            if path.suffix in ('.py', '.tsx') and not prose_like(text):
                continue
            found.extend(check_text(text, relative, line, rules, dynamic, role if role_default == 'prose' else role_default))
    unique = {(v.file, v.line, v.kind, v.text): v for v in found}
    return [v for v in unique.values() if not any(a['file'] == v.file and a['contains'] in v.text for a in rules.get('allow', []))]
