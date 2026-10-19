"""Record synthetic graph-analysis ramp observations; never changes service limits."""
import argparse
import importlib.util
import json
import platform
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run(classes,modules,edge_density):
    sys.path.insert(0,str(ROOT/'backend'))
    benchmark_path=ROOT/'scripts'/'benchmark_scalability.py'
    spec=importlib.util.spec_from_file_location('archintel_benchmark_scalability',benchmark_path)
    benchmark=importlib.util.module_from_spec(spec);spec.loader.exec_module(benchmark)
    fixture=benchmark.fixture
    from app.config import Settings
    from app.services.engine import analyze
    nodes,edges=fixture(classes,modules)
    # Add deterministic extra dependencies to reach a requested target density.
    target=min(classes*max(0.0,edge_density),classes*classes)
    existing={(edge['source'],edge['target']) for edge in edges}
    extra=max(0,int(target)-len(edges))
    index=0
    while extra and index<classes*4:
        source=nodes[index%classes]['fqn'];dest=nodes[(index*7919+17)%classes]['fqn']
        if source!=dest and (source,dest) not in existing:
            edges.append(dict(source=source,target=dest,dependency_type='FIELD_TYPE'));existing.add((source,dest));extra-=1
        index+=1
    start=time.perf_counter();result=analyze(nodes,edges,Settings(_env_file=None));elapsed=time.perf_counter()-start
    graph_bytes=sum(len(part.encode('utf-8')) for part in json.JSONEncoder(separators=(',',':')).iterencode(dict(classes=nodes,edges=edges)))
    return dict(classes=result['summary']['class_count'],edges=result['summary']['typed_dependency_count'],packages=result['summary']['package_count'],seconds=round(elapsed,3),input_graph_mb=round(graph_bytes/1024**2,3))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classes',nargs='+',type=int,default=[10000,25000,50000,100000,200000])
    parser.add_argument('--modules',type=int,default=7)
    parser.add_argument('--edge-density',type=float,default=1.05,help='target dependency pairs per class')
    parser.add_argument('--time-budget-seconds',type=float,default=600)
    parser.add_argument('--memory-budget-mb',type=int,default=4096)
    parser.add_argument('--output',type=Path,default=ROOT/'docs'/'benchmarks'/'ramp-test.json')
    args=parser.parse_args()
    rows=[];last_finished=None
    for size in args.classes:
        try:
            row=run(size,args.modules,args.edge_density)
            row['status']='COMPLETED' if row['seconds']<=args.time_budget_seconds else 'TIME_BUDGET_EXCEEDED'
            rows.append(row)
            if row['status']=='COMPLETED':last_finished=row
            else:break
        except Exception as error:
            rows.append(dict(requested_classes=size,status='FAILED',error_type=type(error).__name__,error=str(error)[:500]));break
    suggestion=None
    if last_finished:
        suggestion=dict(review_required=True,classes=int(last_finished['classes']*.75),edges=int(last_finished['edges']*.75),based_on='75% of largest completed synthetic in-process workload; not a production capacity claim')
    report=dict(kind='synthetic-in-process-analysis-ramp',environment=dict(platform=platform.platform(),python=sys.version.split()[0]),configuration=dict(modules=args.modules,edge_density=args.edge_density,time_budget_seconds=args.time_budget_seconds,memory_budget_mb=args.memory_budget_mb,memory_budget_enforced=False),results=rows,suggestion=suggestion,limitations=['Does not measure upload/extraction, scanner/Neo4j, persistence, concurrent jobs, or telemetry ingestion.','The memory budget is recorded for context but not enforced; run under an OS/container memory limit to test RAM exhaustion safely.','Synthetic results require representative end-to-end ramp tests before deployment limits are set.'])
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
