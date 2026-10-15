"""Deterministic scalability benchmark for ArchIntel's pure analysis pipeline.

Run: python scripts/benchmark_scalability.py --classes 100 500 1000 --repeats 3 --output docs/benchmarks/latest.json
Results are environment-specific observations, not capacity guarantees.
"""
import argparse
import json
import os
import platform
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


def fixture(size:int):
    classes=[]; edges=[]
    for i in range(size):
        name=f'bench.domain{i%20}.Component{i}'
        classes.append(dict(fqn=name,simple_name=f'Component{i}',package_name=f'bench.domain{i%20}',method_count=5,field_count=2,is_abstract=False,is_interface=False,annotations=[]))
        if i:
            edges.append(dict(source=name,target=f'bench.domain{(i-1)%20}.Component{i-1}',dependency_type='METHOD_CALL'))
        if i>3 and i%7==0:
            edges.append(dict(source=name,target=f'bench.domain{(i-3)%20}.Component{i-3}',dependency_type='FIELD_TYPE'))
    return classes,edges


def measure(size,repeats):
    samples=[];result=None
    for _ in range(repeats):
        classes,edges=fixture(size);start=time.perf_counter();result=analyze(classes,edges,Settings(_env_file=None));samples.append(time.perf_counter()-start)
    return dict(requested_classes=size,actual_classes=result['summary']['class_count'],edges=result['summary']['dependency_count'],domains=result['summary']['domain_count'],seconds_median=round(statistics.median(samples),4),seconds_samples=[round(x,4) for x in samples])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--classes',nargs='+',type=int,default=[100,500,1000]);parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.repeats<1 or any(n<1 for n in args.classes):parser.error('classes and repeats must be positive')
    rows=[measure(n,args.repeats) for n in args.classes]
    memory=dict(max_rss_platform_units=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,units='KiB on Linux; bytes on macOS; platform-dependent on Windows') if resource else dict(max_rss_platform_units=None,units='unavailable on this platform')
    report=dict(kind='pure-analysis-scalability-benchmark',environment=dict(platform=platform.platform(),python=sys.version.split()[0],processor=platform.processor() or 'not reported',cpu_count=os.cpu_count()),memory=memory,repeats=args.repeats,results=rows,limitations=['Measures only deterministic in-process architecture analysis; excludes archive validation, jQAssistant, Neo4j extraction, database persistence, API queueing and UI rendering.','Synthetic graph shape and host conditions may differ from customer applications.','Not a capacity, latency, or service-level guarantee.'])
    rendered=json.dumps(report,indent=2)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(rendered+'\n',encoding='utf-8')
    print(rendered)

if __name__=='__main__':main()
