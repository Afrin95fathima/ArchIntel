"""Bounded, read-only Java class-file reader (JVMS chapter 4).

Customer bytecode is parsed as data only: nothing is loaded, linked or executed.
Every list is capped so a hostile or very large class cannot exhaust memory.
"""
from __future__ import annotations

import re
import struct

MAX_CLASS_BYTES = 4 * 1024 * 1024
MAX_SITES_PER_METHOD = 400
MAX_METHODS = 2000

ACC_PUBLIC, ACC_PRIVATE, ACC_PROTECTED, ACC_STATIC, ACC_FINAL = 0x1, 0x2, 0x4, 0x8, 0x10
ACC_BRIDGE, ACC_VARARGS, ACC_INTERFACE, ACC_ABSTRACT = 0x40, 0x80, 0x200, 0x400
ACC_SYNTHETIC, ACC_ANNOTATION, ACC_ENUM = 0x1000, 0x2000, 0x4000


class ClassFormatError(ValueError):
    pass


# Operand byte counts for fixed-length opcodes; -1 marks variable-length instructions.
_LENGTHS = [0] * 256
for _op in list(range(0x10, 0x11)) + [0x12, 0x15, 0x16, 0x17, 0x18, 0x19, 0x36, 0x37, 0x38, 0x39, 0x3a, 0xa9, 0xbc]:
    _LENGTHS[_op] = 1
for _op in [0x11, 0x13, 0x14, 0x84, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xbb, 0xbd, 0xc0, 0xc1, 0xc6, 0xc7] + list(range(0x99, 0xa9)):
    _LENGTHS[_op] = 2
_LENGTHS[0xc5] = 3                       # multianewarray
for _op in (0xb9, 0xba, 0xc8, 0xc9):      # invokeinterface, invokedynamic, goto_w, jsr_w
    _LENGTHS[_op] = 4
_LENGTHS[0xaa] = _LENGTHS[0xab] = _LENGTHS[0xc4] = -1   # tableswitch, lookupswitch, wide
_BRANCHES = set(range(0x99, 0xa7)) | {0xc6, 0xc7}        # conditional branches (if*, ifnull, ifnonnull)
_INVOKES = {0xb6: 'virtual', 0xb7: 'special', 0xb8: 'static', 0xb9: 'interface'}
_FIELDS = {0xb2: 'getstatic', 0xb3: 'putstatic', 0xb4: 'getfield', 0xb5: 'putfield'}


def _mutf8(data: bytes) -> str:
    # Modified UTF-8 encodes NUL as C0 80 and supplementary characters as surrogate pairs.
    return data.replace(b'\xc0\x80', b'\x00').decode('utf-8', 'surrogatepass').encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')


def internal_to_dotted(name: str) -> str:
    return name.replace('/', '.')


_DESC_TYPE = re.compile(r'\[*(?:[BCDFIJSZV]|L[^;]+;)')
_PRIMS = {'B': 'byte', 'C': 'char', 'D': 'double', 'F': 'float', 'I': 'int', 'J': 'long', 'S': 'short', 'Z': 'boolean', 'V': 'void'}


def descriptor_type(token: str) -> str:
    dims = len(token) - len(token.lstrip('['))
    base = token[dims:]
    name = _PRIMS.get(base) or internal_to_dotted(base[1:-1])
    return name + '[]' * dims


def parse_method_descriptor(desc: str) -> tuple[list[str], str]:
    match = re.fullmatch(r'\((.*)\)(.+)', desc or '')
    if not match:
        return [], 'void'
    return [descriptor_type(t) for t in _DESC_TYPE.findall(match.group(1))], descriptor_type(match.group(2))


def signature_types(signature: str | None) -> list[str]:
    """Class names referenced by a generic Signature attribute, including type arguments."""
    if not signature:
        return []
    names = []
    for match in re.finditer(r'(?:^|[(<;:^\[)*+\-])L([A-Za-z0-9_$/]+)', signature):
        names.append(internal_to_dotted(match.group(1)))
    # Nested generic inner types use '.' after type arguments; keep only top-level owner names.
    return sorted(set(names))


def base_type(type_name: str) -> str:
    while type_name.endswith('[]'):
        type_name = type_name[:-2]
    return type_name


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def take(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise ClassFormatError('truncated class file')
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def u1(self) -> int:
        return self.take(1)[0]

    def u2(self) -> int:
        return struct.unpack('>H', self.take(2))[0]

    def u4(self) -> int:
        return struct.unpack('>I', self.take(4))[0]


class ClassFile:
    """Parsed facts of one class file."""

    def __init__(self, data: bytes):
        if len(data) > MAX_CLASS_BYTES:
            raise ClassFormatError('class file exceeds size limit')
        r = _Reader(data)
        if r.u4() != 0xCAFEBABE:
            raise ClassFormatError('not a class file')
        self.minor, self.major = r.u2(), r.u2()
        self.cp: list = [None] * r.u2()
        i = 1
        while i < len(self.cp):
            tag = r.u1()
            if tag == 1:
                self.cp[i] = ('utf8', _mutf8(r.take(r.u2())))
            elif tag in (3, 4):
                raw = r.take(4)
                self.cp[i] = ('int', struct.unpack('>i', raw)[0]) if tag == 3 else ('float', struct.unpack('>f', raw)[0])
            elif tag in (5, 6):
                raw = r.take(8)
                self.cp[i] = ('long', struct.unpack('>q', raw)[0]) if tag == 5 else ('double', struct.unpack('>d', raw)[0])
                i += 1
            elif tag in (7, 8, 16, 19, 20):
                self.cp[i] = ({7: 'class', 8: 'string', 16: 'methodtype', 19: 'module', 20: 'package'}[tag], r.u2())
            elif tag in (9, 10, 11, 12, 17, 18):
                self.cp[i] = ({9: 'field', 10: 'method', 11: 'imethod', 12: 'nat', 17: 'dynamic', 18: 'indy'}[tag], r.u2(), r.u2())
            elif tag == 15:
                self.cp[i] = ('handle', r.u1(), r.u2())
            else:
                raise ClassFormatError('unknown constant pool tag %d' % tag)
            i += 1
        self.access = r.u2()
        self.name = internal_to_dotted(self.class_name(r.u2()))
        super_index = r.u2()
        self.super_name = internal_to_dotted(self.class_name(super_index)) if super_index else None
        self.interfaces = [internal_to_dotted(self.class_name(r.u2())) for _ in range(r.u2())]
        self.fields = [self._member(r, False) for _ in range(r.u2())]
        count = r.u2()
        if count > MAX_METHODS:
            raise ClassFormatError('too many methods')
        self.methods = [self._member(r, True) for _ in range(count)]
        self.attributes = self._attributes(r, 'class')

    # -- constant pool helpers -------------------------------------------------
    def utf8(self, index: int) -> str:
        entry = self.cp[index] if 0 < index < len(self.cp) else None
        if not entry or entry[0] != 'utf8':
            raise ClassFormatError('bad utf8 index')
        return entry[1]

    def class_name(self, index: int) -> str:
        entry = self.cp[index] if 0 < index < len(self.cp) else None
        if not entry or entry[0] != 'class':
            raise ClassFormatError('bad class index')
        name = self.utf8(entry[1])
        if name.startswith('['):           # array class constant
            return base_type(descriptor_type(name)).replace('.', '/')
        return name

    def member_ref(self, index: int) -> tuple[str, str, str]:
        entry = self.cp[index]
        owner = internal_to_dotted(self.class_name(entry[1]))
        nat = self.cp[entry[2]]
        return owner, self.utf8(nat[1]), self.utf8(nat[2])

    # -- members and attributes ------------------------------------------------
    def _member(self, r: _Reader, method: bool) -> dict:
        access, name, desc = r.u2(), self.utf8(r.u2()), self.utf8(r.u2())
        item = dict(access=access, name=name, descriptor=desc)
        item.update(self._attributes(r, 'method' if method else 'field'))
        return item

    def _attributes(self, r: _Reader, scope: str) -> dict:
        out: dict = {}
        for _ in range(r.u2()):
            name, length = self.utf8(r.u2()), r.u4()
            body = _Reader(r.take(length))
            if name in ('RuntimeVisibleAnnotations', 'RuntimeInvisibleAnnotations'):
                out.setdefault('annotations', []).extend(self._annotations(body))
            elif name in ('RuntimeVisibleParameterAnnotations', 'RuntimeInvisibleParameterAnnotations'):
                params = [[self._annotation(body) for _ in range(body.u2())] for _ in range(body.u1())]
                existing = out.setdefault('parameter_annotations', [[] for _ in params])
                for index, values in enumerate(params):
                    if index < len(existing):
                        existing[index].extend(values)
            elif name == 'Signature':
                out['signature'] = self.utf8(body.u2())
            elif name == 'Deprecated':
                out['deprecated'] = True
            elif name == 'SourceFile' and scope == 'class':
                out['source_file'] = self.utf8(body.u2())
            elif name == 'Exceptions' and scope == 'method':
                out['exceptions'] = [internal_to_dotted(self.class_name(body.u2())) for _ in range(body.u2())]
            elif name == 'MethodParameters' and scope == 'method':
                names = []
                for _ in range(body.u1()):
                    index, _flags = body.u2(), body.u2()
                    names.append(self.utf8(index) if index else None)
                out['method_parameters'] = names
            elif name == 'Code' and scope == 'method':
                out.update(self._code(body))
            elif name == 'InnerClasses' and scope == 'class':
                rows = []
                for _ in range(body.u2()):
                    inner, outer, inner_name, flags = body.u2(), body.u2(), body.u2(), body.u2()
                    rows.append(dict(inner=internal_to_dotted(self.class_name(inner)),
                        outer=internal_to_dotted(self.class_name(outer)) if outer else None,
                        simple_name=self.utf8(inner_name) if inner_name else None, access=flags))
                out['inner_classes'] = rows
            elif name == 'EnclosingMethod' and scope == 'class':
                owner, method_index = body.u2(), body.u2()
                nat = self.cp[method_index] if method_index else None
                out['enclosing_method'] = dict(owner=internal_to_dotted(self.class_name(owner)),
                    name=self.utf8(nat[1]) if nat else None, descriptor=self.utf8(nat[2]) if nat else None)
            elif name == 'BootstrapMethods' and scope == 'class':
                methods = []
                for _ in range(body.u2()):
                    handle = body.u2()
                    args = [body.u2() for _ in range(body.u2())]
                    methods.append((handle, args))
                out['bootstrap'] = methods
            elif name == 'NestHost' and scope == 'class':
                out['nest_host'] = internal_to_dotted(self.class_name(body.u2()))
        return out

    def _annotations(self, r: _Reader) -> list[dict]:
        return [self._annotation(r) for _ in range(r.u2())]

    def _annotation(self, r: _Reader) -> dict:
        type_name = descriptor_type(self.utf8(r.u2()))
        values = {}
        for _ in range(r.u2()):
            key = self.utf8(r.u2())
            values[key] = self._element(r)
        return dict(type=type_name, values=values)

    def _element(self, r: _Reader):
        tag = chr(r.u1())
        if tag in 'BCDFIJSZ':
            value = self.cp[r.u2()][1]
            return bool(value) if tag == 'Z' else chr(value) if tag == 'C' else value
        if tag == 's':
            return self.utf8(r.u2())
        if tag == 'e':
            enum_type, const = descriptor_type(self.utf8(r.u2())), self.utf8(r.u2())
            return enum_type.rsplit('.', 1)[-1] + '.' + const
        if tag == 'c':
            return descriptor_type(self.utf8(r.u2()))
        if tag == '@':
            return self._annotation(r)
        if tag == '[':
            return [self._element(r) for _ in range(r.u2())]
        raise ClassFormatError('bad annotation element tag')

    def _code(self, r: _Reader) -> dict:
        r.u2(); r.u2()                                  # max_stack, max_locals
        code = r.take(r.u4())
        for _ in range(r.u2()):                          # exception table
            r.take(8)
        lines: list[tuple[int, int]] = []
        local_vars: dict[int, str] = {}
        for _ in range(r.u2()):
            name, length = self.utf8(r.u2()), r.u4()
            body = _Reader(r.take(length))
            if name == 'LineNumberTable':
                lines = sorted((body.u2(), body.u2()) for _ in range(body.u2()))
            elif name == 'LocalVariableTable':
                for _ in range(body.u2()):
                    start, _length, var, _desc, slot = body.u2(), body.u2(), self.utf8(body.u2()), body.u2(), body.u2()
                    if start == 0:
                        local_vars[slot] = self.utf8(_desc) and var
        return dict(code_length=len(code), local_vars=local_vars, **self._walk(code, lines))

    def _walk(self, code: bytes, lines: list[tuple[int, int]]) -> dict:
        def line_at(pc: int):
            current = None
            for start, number in lines:
                if start > pc:
                    break
                current = number
            return current
        invokes, fields, types, indy = [], [], [], []
        branches, pc, truncated = 0, 0, False
        while pc < len(code):
            op = code[pc]
            length = _LENGTHS[op]
            if op in _BRANCHES:
                branches += 1
            if op in _INVOKES or op in _FIELDS or op in (0xbb, 0xc0, 0xc1, 0xbd, 0xc5, 0x12, 0x13):
                index = code[pc + 1] if op == 0x12 else struct.unpack('>H', code[pc + 1:pc + 3])[0]
                entry = self.cp[index] if 0 < index < len(self.cp) else None
                if len(invokes) + len(fields) + len(types) >= MAX_SITES_PER_METHOD:
                    truncated = True
                elif op in _INVOKES and entry and entry[0] in ('method', 'imethod'):
                    owner, name, desc = self.member_ref(index)
                    invokes.append(dict(owner=owner, name=name, descriptor=desc, kind=_INVOKES[op], line=line_at(pc)))
                elif op in _FIELDS and entry and entry[0] == 'field':
                    owner, name, desc = self.member_ref(index)
                    fields.append(dict(owner=owner, name=name, descriptor=desc, kind=_FIELDS[op], line=line_at(pc)))
                elif entry and entry[0] == 'class':
                    types.append(dict(type=internal_to_dotted(self.class_name(index)),
                        kind={0xbb: 'new', 0xc0: 'checkcast', 0xc1: 'instanceof'}.get(op, 'constant'), line=line_at(pc)))
            elif op == 0xba:
                index = struct.unpack('>H', code[pc + 1:pc + 3])[0]
                entry = self.cp[index] if 0 < index < len(self.cp) else None
                if entry and entry[0] == 'indy':
                    indy.append(dict(bootstrap=entry[1], name=self.utf8(self.cp[entry[2]][1]), line=line_at(pc)))
            if length >= 0:
                pc += 1 + length
            elif op == 0xc4:                             # wide
                pc += 6 if code[pc + 1] == 0x84 else 4
            else:
                pad = (4 - (pc + 1) % 4) % 4
                base = pc + 1 + pad
                if op == 0xaa:
                    low, high = struct.unpack('>ii', code[base + 4:base + 12])
                    branches += max(0, high - low + 1)
                    pc = base + 12 + 4 * (high - low + 1)
                else:
                    pairs = struct.unpack('>i', code[base + 4:base + 8])[0]
                    branches += max(0, pairs)
                    pc = base + 8 + 8 * pairs
        return dict(invokes=invokes, field_access=fields, type_refs=types, indy=indy, branch_count=branches,
            line_range=[lines[0][1], max(n for _, n in lines)] if lines else None, sites_truncated=truncated)

    # -- derived views -----------------------------------------------------------
    def lambda_targets(self) -> dict[int, dict]:
        """Map bootstrap index -> implementation method handle for LambdaMetafactory call sites."""
        out = {}
        for index, (handle, args) in enumerate(self.attributes.get('bootstrap', [])):
            try:
                kind, ref = self.cp[handle][1], self.cp[handle][2]
                owner, name, _ = self.member_ref(ref)
                if not name.endswith('metafactory'):
                    continue
                for arg in args:
                    entry = self.cp[arg]
                    if entry and entry[0] == 'handle':
                        target = self.member_ref(entry[2])
                        out[index] = dict(owner=target[0], name=target[1], descriptor=target[2])
            except (TypeError, IndexError, ClassFormatError):
                continue
        return out


def parse(data: bytes) -> ClassFile:
    try:
        return ClassFile(data)
    except (struct.error, IndexError, TypeError, UnicodeError) as error:
        raise ClassFormatError('malformed class file') from error


def parameter_names(method: dict, descriptor: str, static: bool) -> list[str | None]:
    """Parameter names from MethodParameters (-parameters) or, failing that, the LocalVariableTable (-g)."""
    count = len(parse_method_descriptor(descriptor)[0])
    names = method.get('method_parameters')
    if names and len(names) == count:
        return names
    local = method.get('local_vars') or {}
    if not local:
        return [None] * count
    out, slot = [], 0 if static else 1
    for token in _DESC_TYPE.findall(re.fullmatch(r'\((.*)\).+', descriptor).group(1)):
        out.append(local.get(slot))
        slot += 2 if token in ('J', 'D') else 1
    return out
