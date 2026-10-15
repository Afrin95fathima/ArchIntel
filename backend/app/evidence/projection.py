"""Fixed, tenant/version-scoped Neo4j projection and bounded graph queries."""
import json
from neo4j import GraphDatabase
from sqlalchemy import select
from .models import Projection,ArchitectureVersion
from .builder import canonical,digest
from fastapi import HTTPException


def connect(config):
    if not config.knowledge_graph_enabled:raise RuntimeError('GRAPH_DISABLED')
    password=config.knowledge_graph_password.get_secret_value()
    if not password and config.knowledge_graph_password_file:
        password=config.knowledge_graph_password_file.read_text(encoding='utf-8').strip()
    if not password:raise RuntimeError('GRAPH_CREDENTIAL_UNAVAILABLE')
    return GraphDatabase.driver(config.knowledge_graph_uri,auth=(config.knowledge_graph_user,password),connection_timeout=3,max_connection_pool_size=4,connection_acquisition_timeout=5,max_transaction_retry_time=3)


def scope(item):return item.tenant_id+':'+item.id

def apply(config,item):
    graph=item.document['graph'];partition=scope(item);hashed=digest(graph)
    with connect(config) as driver,driver.session(database='neo4j') as neo:
        neo.run('CREATE CONSTRAINT archintel_entity_id IF NOT EXISTS FOR (n:ArchIntelEntity) REQUIRE n.id IS UNIQUE').consume()
        neo.run('CREATE CONSTRAINT archintel_projection_scope IF NOT EXISTS FOR (n:ArchIntelProjection) REQUIRE n.scope IS UNIQUE').consume()
        neo.run('CREATE INDEX archintel_entity_scope IF NOT EXISTS FOR (n:ArchIntelEntity) ON (n.scope)').consume()
        def write(tx):
            tx.run('MATCH (n:ArchIntelEntity {scope:$scope}) DETACH DELETE n',scope=partition).consume()
            for start in range(0,len(graph['nodes']),500):
                rows=[dict(id=n['id'],kind=n['kind'],name=n['name'],payload=canonical(n)) for n in graph['nodes'][start:start+500]]
                tx.run('UNWIND $rows AS row CREATE (n:ArchIntelEntity {id:row.id,scope:$scope,kind:row.kind,name:row.name,payload:row.payload})',rows=rows,scope=partition).consume()
            for start in range(0,len(graph['edges']),1000):
                tx.run('UNWIND $rows AS row MATCH (a:ArchIntelEntity {id:row.source,scope:$scope}), (b:ArchIntelEntity {id:row.target,scope:$scope}) CREATE (a)-[:ARCH_LINK {id:row.id,scope:$scope,kind:row.kind}]->(b)',rows=graph['edges'][start:start+1000],scope=partition).consume()
            tx.run('MERGE (p:ArchIntelProjection {scope:$scope}) SET p.content_hash=$hash,p.nodes=$nodes,p.edges=$edges',scope=partition,hash=hashed,nodes=len(graph['nodes']),edges=len(graph['edges'])).consume()
        neo.execute_write(write)


def project(db,item,config):
    job=db.scalar(select(Projection).where(Projection.version_id==item.id))
    job.attempts+=1
    try:
        apply(config,item);job.state='APPLIED';job.error_code=None
    except Exception as error:
        job.state='FAILED';job.error_code=type(error).__name__  # Never expose connection credentials/payload.
    db.commit()
    return dict(state=job.state,attempts=job.attempts,error_code=job.error_code,content_hash=job.content_hash)


def checked(neo,item):
    partition=scope(item)
    marker=neo.run('MATCH (p:ArchIntelProjection {scope:$scope}) RETURN p.content_hash AS hash,p.nodes AS nodes,p.edges AS edges',scope=partition).single()
    if not marker or marker['hash']!=digest(item.document['graph']):raise HTTPException(409,'Graph projection is missing or stale. Rebuild this version.')
    count=neo.run('MATCH (n:ArchIntelEntity {scope:$scope}) RETURN count(n) AS count',scope=partition).single()['count']
    edges=neo.run('MATCH ()-[r:ARCH_LINK {scope:$scope}]->() RETURN count(r) AS count',scope=partition).single()['count']
    if count!=marker['nodes'] or edges!=marker['edges']:raise HTTPException(409,'Graph projection is incomplete. Rebuild this version.')
    return marker


def query(config,item,limit=150,root=None):
    try:
        with connect(config) as driver,driver.session(database='neo4j') as neo:
            marker=checked(neo,item);partition=scope(item)
            if root:
                rows=list(neo.run('MATCH (a:ArchIntelEntity {scope:$scope,id:$root}) RETURN a.payload AS payload',scope=partition,root=root))
                if rows and limit>1:
                    rows+=list(neo.run('MATCH (a:ArchIntelEntity {scope:$scope,id:$root})-[:ARCH_LINK]-(b:ArchIntelEntity {scope:$scope}) WHERE b.id<>$root RETURN DISTINCT b.payload AS payload ORDER BY payload LIMIT $limit',scope=partition,root=root,limit=limit-1))
            else:
                rows=list(neo.run('MATCH (n:ArchIntelEntity {scope:$scope}) RETURN n.payload AS payload ORDER BY n.id LIMIT $limit',scope=partition,limit=limit))
            nodes=[json.loads(r['payload']) for r in rows];ids=[n['id'] for n in nodes]
            edges=[dict(r) for r in neo.run('MATCH (a:ArchIntelEntity {scope:$scope})-[r:ARCH_LINK {scope:$scope}]->(b:ArchIntelEntity {scope:$scope}) WHERE a.id IN $ids AND b.id IN $ids RETURN r.id AS id,a.id AS source,b.id AS target,r.kind AS kind ORDER BY r.id LIMIT 1000',scope=partition,ids=ids)]
            return dict(nodes=nodes,edges=edges,projection='CURRENT',content_hash=marker['hash'],total_nodes=marker['nodes'],total_edges=marker['edges'],truncated=len(nodes)<marker['nodes'] or len(edges)<marker['edges'],scope='ONE_HOP' if root else 'BOUNDED_VERSION')
    except HTTPException:raise
    except Exception:raise HTTPException(503,'Knowledge graph unavailable. Canonical evidence remains available; retry projection after recovery.')


def sweep(sessions,config):
    with sessions() as db:
        jobs=list(db.scalars(select(Projection).where(Projection.state.in_(['PENDING','FAILED']),Projection.attempts<10).order_by(Projection.created_at).limit(2)))
        for job in jobs:
            item=db.get(ArchitectureVersion,job.version_id)
            project(db,item,config)
