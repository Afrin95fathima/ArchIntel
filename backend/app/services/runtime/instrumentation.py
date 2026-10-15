"""Deterministic, bounded instrumentation plans; no source loading or execution."""
import hashlib
import json
import re
from .entry_points import METHOD_ENTRY_ANNOTATIONS, is_method_entry_point

VERSION='runtime-plan-2'
BOUNDARIES={'Controller','RestController','Service','Repository','Component','Configuration'}
ENTRY_POINTS=METHOD_ENTRY_ANNOTATIONS


def in_package(identity,prefixes):
    return any(identity==p.rstrip('.*') or identity.startswith(p.rstrip('.*')+'.') for p in prefixes)


def build_plan(static,settings):
    included=settings.get('include_packages',[]);excluded=settings.get('exclude_packages',[]);mode=settings.get('mode','BOUNDARY')
    cyclic={n for c in static['cycles'] if c['level']=='CLASS' for n in c['members']}
    selected=[];omitted={};method_count=0;encoded_bytes=0
    def omit(reason):omitted[reason]=omitted.get(reason,0)+1
    for cls in sorted(static['classes'],key=lambda c:c['id']):
        identity=cls['id']
        if not re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$.]*',identity):omit('UNSUPPORTED_CLASS_NAME');continue
        if included and not in_package(identity,included):omit('OUTSIDE_INCLUDE_SCOPE');continue
        if in_package(identity,excluded):omit('EXCLUDED_PACKAGE');continue
        boundary=any(a.rsplit('.',1)[-1] in BOUNDARIES for a in cls.get('annotations',[]))
        entry=any(is_method_entry_point(m.get('annotations',[])) for m in cls.get('methods',[]))
        important=identity in cyclic or cls.get('metrics',{}).get('fan_out',0)>5
        if not (boundary or entry or mode=='DEEP' or mode=='STANDARD' and important):omit('OUTSIDE_SELECTED_DEPTH');continue
        methods=sorted({m['name'] for m in cls.get('methods',[]) if m.get('name') and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',m['name'])})
        if not methods:omit('NO_INSTRUMENTABLE_METHOD_INVENTORY');continue
        if len(methods)>100:omit('METHOD_NAMES_TRUNCATED');methods=methods[:100]
        size=len((identity+'['+','.join(methods)+'];').encode())
        if len(selected)>=200 or method_count+len(methods)>3000 or encoded_bytes+size>24000:omit('PLAN_BUDGET');continue
        method_count+=len(methods);encoded_bytes+=size
        selected.append(dict(class_name=identity,methods=','.join(methods),reason='Annotated application boundary' if boundary else 'Annotated entry point' if entry else 'Static importance' if important else 'Explicit deep tracing',priority=1 if boundary or entry else 2))
    plan=dict(version=VERSION,mode=mode,include_packages=included,exclude_packages=excluded,classes=selected,
              selected_method_names=method_count,encoded_bytes=encoded_bytes,omissions=omitted,
              limitations=['Method-name instrumentation includes every overload; exact overload coverage requires descriptor telemetry.',
                           'Framework auto-instrumentation may emit spans outside this method plan. Review agent overhead before using it.'])
    plan['sha256']=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return plan
