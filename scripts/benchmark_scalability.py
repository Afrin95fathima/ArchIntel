"""Deterministic synthetic benchmark for ArchIntel's pure analysis pipeline.

Example: python scripts/benchmark_scalability.py --classes 100 1000 --modules 7 --repeats 3
Scale shape: python scripts/benchmark_scalability.py --classes 280000 --modules 7 --repeats 1

The scale shape can require substantial memory. Results measure the in-process
analysis stage only; they are observations, not capacity guarantees.
"""
import argparse
import cProfile
import io
import json
import math
import os
import platform
import pstats
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import Settings
from app.services.engine import analyze

try:
    import resource
except ImportError:  # Windows does not expose getrusage in the standard library.
    resource = None


def peak_memory():
    if resource:
        return dict(value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            units='KiB on Linux; bytes on macOS; platform-dependent on other POSIX systems')
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
                ('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
                ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
        psapi=ctypes.WinDLL('psapi',use_last_error=True)
        kernel32.GetCurrentProcess.restype=wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
        process=kernel32.GetCurrentProcess()
        ok=psapi.GetProcessMemoryInfo(process,ctypes.byref(counters),counters.cb)
        if ok:
            return dict(value=int(counters.PeakWorkingSetSize),units='bytes of peak process working set')
    return dict(value=None,units='unavailable on this platform')


def fixture(size:int, modules:int=7):
    """Create a connected modular graph with bounded cross-module coupling.

    Each module contains a dependency chain and package groups of 1,000
    classes. At roughly forty evenly spaced points, adjacent modules also
    depend on one another, creating deterministic cross-module cycles.
    """
    if size < 1 or modules < 1:
        raise ValueError('size and modules must be positive')
    base, remainder=divmod(size,modules)
    counts=[base+(1 if module<remainder else 0) for module in range(modules)]
    classes=[]
    edges=[]
    checkpoint=max(1,math.ceil(max(counts,default=1)/40))
    for module,count in enumerate(counts):
        for local in range(count):
            name=f'bench.module{module}.package{local//1000}.Component{module}_{local}'
            classes.append(dict(fqn=name,simple_name=f'Component{module}_{local}',package_name=f'bench.module{module}.package{local//1000}',method_count=5,field_count=2,is_abstract=False,is_interface=False,annotations=[]))
            if local:
                edges.append(dict(source=name,target=f'bench.module{module}.package{(local-1)//1000}.Component{module}_{local-1}',dependency_type='METHOD_CALL'))
            selected_checkpoint=(local==count//2 if count<=40 else local%checkpoint==0)
            if local and selected_checkpoint:
                following=(module+1)%modules
                peer_count=counts[following]
                if local<peer_count:
                    edges.append(dict(source=name,target=f'bench.module{following}.package{local//1000}.Component{following}_{local}',dependency_type='FIELD_TYPE'))
    return classes,edges


def encoded_size(value)->int:
    """Return compact JSON size without retaining a second full result string."""
    return sum(len(part.encode('utf-8')) for part in json.JSONEncoder(separators=(',',':')).iterencode(value))


def measure(size:int,repeats:int,modules:int):
    samples=[]
    result=None
    fixture_edges=0
    for _ in range(repeats):
        classes,edges=fixture(size,modules)
        fixture_edges=len(edges)
        start=time.perf_counter()
        result=analyze(classes,edges,Settings(_env_file=None))
        samples.append(time.perf_counter()-start)
        del classes,edges
    summary=result['summary']
    package_sizes={}
    for row in result['metrics']:
        package_sizes[row['entity_id']]=row['class_count']
    cycle_members=sum(cycle['node_count'] for cycle in result['cycles'] if cycle['level']=='CLASS')
    return dict(requested_classes=size,actual_classes=summary['class_count'],modules=modules,
        packages=summary['package_count'],dependency_pairs=summary['dependency_count'],
        typed_dependency_edges=summary['typed_dependency_count'],generated_edges=fixture_edges,
        cross_module_edges=sum(1 for edge in result['edges'] if edge['source'].split('.')[1]!=edge['target'].split('.')[1]),
        domains=summary['domain_count'],class_scc_count=summary['class_scc_count'],
        package_scc_count=summary['package_scc_count'],reported_class_cycle_members=cycle_members,
        largest_package_classes=max(package_sizes.values(),default=0),issues=summary['issue_count'],
        dependency_edges_per_class=round(summary['dependency_count']/max(summary['class_count'],1),4),
        result_json_bytes=encoded_size(result),seconds_median=round(statistics.median(samples),4),
        seconds_samples=[round(value,4) for value in samples])


def profile(size:int,modules:int):
    classes,edges=fixture(size,modules)
    profiler=cProfile.Profile()
    profiler.enable()
    analyze(classes,edges,Settings(_env_file=None))
    profiler.disable()
    stats=pstats.Stats(profiler,stream=io.StringIO()).sort_stats('cumulative')
    rows=[]
    for (filename,line,name),(primitive,total,own,cumulative,_callers) in list(stats.stats.items()):
        rows.append(dict(function=f'{Path(filename).name}:{line}({name})',calls=total,
            own_seconds=round(own,5),cumulative_seconds=round(cumulative,5)))
    rows.sort(key=lambda row:row['cumulative_seconds'],reverse=True)
    return dict(classes=size,modules=modules,top_functions=rows[:10])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classes',nargs='+',type=int,default=[100,500,1000],help='total class counts for each workload')
    parser.add_argument('--modules',type=int,default=7,help='number of synthetic modules (default: 7)')
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--profile-classes',type=int,help='separately profile one workload and report its top cumulative functions')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.repeats<1 or args.modules<1 or any(n<1 for n in args.classes) or (args.profile_classes is not None and args.profile_classes<1):
        parser.error('classes, modules, and repeats must be positive')
    rows=[measure(n,args.repeats,args.modules) for n in args.classes]
    memory=peak_memory()
    report=dict(kind='synthetic-modular-analysis-benchmark',environment=dict(platform=platform.platform(),
        python=sys.version.split()[0],processor=platform.processor() or 'not reported',cpu_count=os.cpu_count()),
        workload=dict(module_count=args.modules,package_target_classes=1000,cross_module_checkpoint_target='up to 40 per module'),
        memory=memory,repeats=args.repeats,results=rows,
        profile=profile(args.profile_classes,args.modules) if args.profile_classes else None,limitations=[
            'Measures deterministic in-process architecture analysis; excludes archive validation, jQAssistant, Neo4j extraction, database persistence, API queueing and UI rendering.',
            'Synthetic graph shape and host conditions may differ from customer applications.',
            'Memory is process high-water RSS/working set after all cases; it is not a per-case allocation profile.',
            'This is not a capacity, latency, or service-level guarantee.'])
    rendered=json.dumps(report,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(rendered+'\n',encoding='utf-8')
    print(rendered)


if __name__=='__main__':
    main()
