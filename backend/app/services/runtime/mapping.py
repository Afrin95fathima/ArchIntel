"""Conservative class identity matching; unresolved identities stay visible."""
import re


GENERATED_SUFFIX = re.compile(r'(?:\$\$Lambda(?:\$\d+)?(?:[./]0x[0-9a-fA-F]+)?|\$\$(?:FastClassBy|EnhancerBy)(?:Spring)?CGLIB\$\$[A-Za-z0-9]+|'
    r'\$HibernateProxy\$[A-Za-z0-9]+|_\$\$_jvst[A-Za-z0-9_]*|\$ByteBuddy\$[A-Za-z0-9]+)$')


def _nested_candidate(name: str, classes: dict) -> str | None:
    """com.x.Outer.Inner -> com.x.Outer$Inner, accepted only when exactly one binary name matches."""
    parts = name.split('.')
    for split in range(len(parts) - 1, 0, -1):
        candidate = '.'.join(parts[:split]) + '$' + '$'.join(parts[split:])
        if candidate in classes:
            return candidate
    return None


def map_class(identity: str | None, classes: dict) -> dict:
    result = dict(runtime_identity=identity,static_id=None,state='UNRESOLVED',rule=None,confidence=0.,evidence=[])
    if not identity:
        return dict(result,evidence=['Telemetry did not supply code.namespace or code.function for this span.'])
    if identity in classes:
        return dict(result,static_id=identity,state='EXACT',rule='exact',confidence=1.,evidence=['Exact fully qualified class match.'])
    normalized = identity.replace('/', '.')
    if normalized.startswith('L') and normalized.endswith(';'): normalized = normalized[1:-1]
    if normalized in classes:
        return dict(result,static_id=normalized,state='NORMALIZED',rule='normalized',confidence=1.,evidence=['JVM internal-name/descriptor normalization.'])
    proxy = re.sub(r'\$\$(?:SpringCGLIB\$\$\d+|EnhancerBySpringCGLIB\$\$[a-zA-Z0-9]+)$','',normalized)
    if proxy != normalized and proxy in classes:
        return dict(result,static_id=proxy,state='PROXY_RESOLVED',rule='proxy_suffix',confidence=.9,evidence=['Recognized Spring subclass proxy suffix with exact existing base class.'])
    generated = GENERATED_SUFFIX.sub('',normalized)
    if generated != normalized and generated in classes:
        lambda_class = '$$Lambda' in normalized
        return dict(result,static_id=generated,state='LAMBDA_RESOLVED' if lambda_class else 'PROXY_RESOLVED',rule='lambda_suffix' if lambda_class else 'proxy_suffix',confidence=.7,
            evidence=['Runtime-generated %s of an existing class; resolved to its declaring class, not to a specific method.' % ('lambda class' if lambda_class else 'proxy or subclass')])
    nested = _nested_candidate(normalized,classes)
    if nested:
        return dict(result,static_id=nested,state='NESTED_RESOLVED',rule='nested_name',confidence=.95,
            evidence=['Canonical dotted nested-class name matched the binary name %s.' % nested])
    return dict(result,evidence=[f'No unambiguous static class match for {identity}; it is not forced by simple name.'])


GENERATED_MARKERS = ('$Proxy', '$$', '$Lambda', '$HibernateProxy$', '$ByteBuddy$', '_$$_jvst')
CLOSE_MATCH = .85


def closest_candidate(identity: str, classes) -> tuple[str | None, float]:
    """Most similar scanned class name and its difflib ratio (0-1). Reported, never used to map."""
    from difflib import SequenceMatcher
    target = identity.replace('/', '.')
    matcher = SequenceMatcher(None)
    matcher.set_seq2(target)
    best, best_ratio = None, 0.
    for candidate in classes:
        matcher.set_seq1(candidate)
        if matcher.real_quick_ratio() <= best_ratio or matcher.quick_ratio() <= best_ratio:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best, round(best_ratio, 3)


def unresolved_reason(identity: str | None, classes) -> dict:
    """Why a class identity did not map: a reason code, the closest static candidate and its similarity."""
    if not identity:
        return dict(reason_code='NO_CODE_ATTRIBUTES', closest_candidate=None, similarity=None)
    candidate, ratio = closest_candidate(identity, classes)
    if any(marker in identity for marker in GENERATED_MARKERS):
        code = 'PROXY_OR_GENERATED_CLASS'
    elif candidate and ratio >= CLOSE_MATCH:
        code = 'NAME_MISMATCH_CLOSE_CANDIDATE'
    else:
        code = 'CLASS_NOT_IN_SCANNED_ARTIFACT'
    return dict(reason_code=code, closest_candidate=candidate, similarity=ratio if candidate else None)


PRIMITIVES={'void':'V','boolean':'Z','byte':'B','char':'C','short':'S','int':'I','long':'J','float':'F','double':'D'}
JVM_TYPE=r'(?:[BCDFIJSZ]|L[A-Za-z_$][A-Za-z0-9_$/]*;)'
DESCRIPTOR=re.compile(r'^\((?:\[*'+JVM_TYPE+r')*\)(?:V|\[*'+JVM_TYPE+r')$')


def method_descriptor(method):
    explicit=method.get('descriptor')
    if explicit and DESCRIPTOR.fullmatch(explicit):return explicit
    signature=method.get('signature') or ''
    match=re.fullmatch(r'([^ ]+)\s+[^ (]+\(([^()]*)\)',signature)
    if not match:return None
    def convert(value):
        value=value.strip().replace('...','[]');dimensions=0
        while value.endswith('[]'):dimensions+=1;value=value[:-2]
        if value in PRIMITIVES:
            base=PRIMITIVES[value]
            if dimensions and base=='V':return None
        elif re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$.]*',value) and '.' in value:
            base='L'+value.replace('.','/')+';'
        else:return None  # Do not guess an unqualified class or generic type.
        return '['*dimensions+base
    parts=[convert(p) for p in match[2].split(',')] if match[2].strip() else []
    result=convert(match[1])
    if result is None or any(p is None or p=='V' for p in parts):return None
    candidate='('+''.join(parts)+')'+result
    return candidate if DESCRIPTOR.fullmatch(candidate) else None


def map_method(event,classes):
    owner=map_class(event.get('class_name'),classes)['static_id']
    base=dict(static_class=owner,signature=None,state='UNRESOLVED')
    if not owner or not event.get('method_name'):return base
    methods=classes[owner].get('methods')
    if methods is None:return dict(base,state='UNAVAILABLE')
    candidates=[m for m in methods if m.get('name')==event['method_name'] and m.get('signature')]
    descriptor=event.get('method_descriptor') or event.get('attributes',{}).get('code.method.descriptor')
    if event.get('invalid_method_descriptor'):return base
    if descriptor:
        candidates=[m for m in candidates if method_descriptor(m)==descriptor]
        state='EXACT_DESCRIPTOR'
    else:state='UNIQUE_NAME'
    signatures={m['signature'] for m in candidates}
    if len(signatures)==1:return dict(base,signature=next(iter(signatures)),state=state)
    return dict(base,state='AMBIGUOUS' if len(signatures)>1 else 'UNRESOLVED')
