"""Synthetic-only SQLite migration verifier; never accepts a connection string."""
import hashlib
import json
import sqlite3
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from uuid import UUID


class FixtureError(ValueError):
    pass


SQLITE_TYPES={'INT16':'INTEGER','INT32':'INTEGER','INT64':'INTEGER','STRING':'TEXT','BOOLEAN':'INTEGER',
    'DECIMAL':'NUMERIC','FLOAT':'REAL','DATE':'TEXT','TIMESTAMP':'TEXT','TIME':'TEXT','UUID':'TEXT','JSON':'TEXT','BINARY':'BLOB'}
IDENT=re.compile(r'^[A-Za-z_][A-Za-z0-9_$]{0,119}$')


def _q(value):
    if not isinstance(value,str) or not IDENT.fullmatch(value): raise FixtureError('UNSUPPORTED_IDENTIFIER')
    return '"'+value.replace('"','""')+'"'


def _convert(value, target_type):
    if value is None: return None
    if target_type in ('INT16','INT32','INT64'):
        if isinstance(value,bool): raise FixtureError('INVALID_INTEGER_CONVERSION')
        return int(value)
    if target_type=='BOOLEAN':
        if value not in (True,False,0,1,'true','false','0','1'): raise FixtureError('INVALID_BOOLEAN_CONVERSION')
        return 1 if value in (True,1,'true','1') else 0
    if target_type=='DECIMAL':
        try:return str(Decimal(str(value)))
        except InvalidOperation as exc: raise FixtureError('INVALID_DECIMAL_CONVERSION') from exc
    if target_type=='FLOAT': return float(value)
    if target_type=='DATE':
        try:return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc: raise FixtureError('INVALID_DATE_CONVERSION') from exc
    if target_type=='TIMESTAMP':
        try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).isoformat()
        except ValueError as exc: raise FixtureError('INVALID_TIMESTAMP_CONVERSION') from exc
    if target_type=='TIME':
        try:return time.fromisoformat(str(value)).isoformat()
        except ValueError as exc: raise FixtureError('INVALID_TIME_CONVERSION') from exc
    if target_type=='UUID':
        try:return str(UUID(str(value)))
        except ValueError as exc: raise FixtureError('INVALID_UUID_CONVERSION') from exc
    if target_type=='JSON':
        return value if isinstance(value,str) else json.dumps(value,sort_keys=True,separators=(',',':'))
    if target_type=='BINARY':
        if not isinstance(value,(bytes,bytearray)): raise FixtureError('INVALID_BINARY_CONVERSION')
        return bytes(value)
    if target_type=='STRING': return str(value)
    raise FixtureError('UNKNOWN_TARGET_TYPE')


def _create_table(db, prefix, table, columns, primary_key, foreign_keys):
    definitions=[]
    for col in columns:
        typ=SQLITE_TYPES.get(col.get('data_type') or col.get('type'))
        if not typ: raise FixtureError('UNKNOWN_COLUMN_TYPE')
        definitions.append(f"{_q(col['name'])} {typ}"+(' NOT NULL' if not col.get('nullable',True) else ''))
    if primary_key:
        definitions.append('PRIMARY KEY ('+', '.join(_q(c) for c in primary_key)+')')
    for fk in foreign_keys:
        source_cols=fk.get('columns') or []
        target_cols=fk.get('target_columns') or []
        target_table=fk.get('target_table')
        if not source_cols or len(source_cols)!=len(target_cols) or not target_table: raise FixtureError('INVALID_FOREIGN_KEY_DECLARATION')
        definitions.append('FOREIGN KEY ('+', '.join(_q(c) for c in source_cols)+') REFERENCES '+_q(prefix+target_table)+' ('+', '.join(_q(c) for c in target_cols)+') DEFERRABLE INITIALLY DEFERRED')
    db.execute('CREATE TABLE '+_q(prefix+table)+' ('+', '.join(definitions)+')')


def execute(plan, rows):
    """Execute a reviewed proposal in an ephemeral SQLite memory database."""
    source_schema=plan.get('source_schema') or []
    target_schema=plan.get('target_schema') or []
    if not source_schema or not target_schema: raise FixtureError('SCHEMA_NOT_EXECUTABLE')
    known={x['name'].casefold():x for x in source_schema}
    if any(name.casefold() not in known for name in rows): raise FixtureError('FIXTURE_HAS_UNKNOWN_SOURCE_TABLE')
    if any(not isinstance(items,list) for items in rows.values()): raise FixtureError('FIXTURE_ROWS_INVALID')
    db=sqlite3.connect(':memory:')
    try:
        db.execute('PRAGMA foreign_keys=ON')
        # Both source and target schemas are built inside this process only.
        for entity in source_schema:
            _create_table(db,'src__',entity['name'],entity['columns'],entity.get('primary_key',[]),entity.get('foreign_keys',[]))
        for table in target_schema:
            _create_table(db,'tgt__',table['name'],table['columns'],table.get('primary_key',[]),table.get('foreign_keys',[]))
        source_counts={}
        for entity in source_schema:
            name=entity['name']; records=rows.get(name,[]); cols=[c['name'] for c in entity['columns']]
            for row in records:
                if set(row)-set(cols): raise FixtureError('FIXTURE_HAS_UNKNOWN_COLUMN')
            if records:
                names=', '.join(_q(c) for c in cols); placeholders=', '.join('?' for _ in cols)
                db.executemany('INSERT INTO '+_q('src__'+name)+' ('+names+') VALUES ('+placeholders+')',[[row.get(c) for c in cols] for row in records])
            source_counts[name]=len(records)
        db.commit()
        table_by_source={x['source_resource'].casefold():x for x in target_schema}
        maps=plan.get('mappings',[]); map_by_table={}
        for m in maps: map_by_table.setdefault(m['source_table'].casefold(),[]).append(m)
        target_counts={}; conversion_errors=[]
        for entity in source_schema:
            source_name=entity['name']; target=table_by_source.get(source_name.casefold())
            if not target: raise FixtureError('TARGET_TABLE_MAPPING_MISSING')
            mapping=map_by_table.get(source_name.casefold(),[])
            if not mapping: raise FixtureError('COLUMN_MAPPING_MISSING')
            source_cols=[m['source_column'] for m in mapping]; target_cols=[m['target_column'] for m in mapping]
            if any(m.get('target_type') in (None,'UNKNOWN','REVIEW_REQUIRED') for m in mapping): raise FixtureError('TARGET_TYPE_UNRESOLVED')
            result=[]
            for row in rows.get(source_name,[]):
                converted=[]
                for m in mapping:
                    try: converted.append(_convert(row.get(m['source_column']),m['target_type']))
                    except FixtureError as exc:
                        conversion_errors.append(dict(table=source_name,column=m['source_column'],code=str(exc)))
                        raise
                result.append(converted)
            if result:
                names=', '.join(_q(c) for c in target_cols); placeholders=', '.join('?' for _ in target_cols)
                db.executemany('INSERT INTO '+_q('tgt__'+target['name'])+' ('+names+') VALUES ('+placeholders+')',result)
            target_counts[source_name]=len(result)
        db.commit()
        foreign_errors=db.execute('PRAGMA foreign_key_check').fetchall()
        checks=[]
        checks.append(dict(name='SOURCE_AND_TARGET_ROW_COUNTS',status='PASS' if source_counts==target_counts else 'FAIL',source=source_counts,target=target_counts))
        checks.append(dict(name='KEYS_AND_UNIQUENESS',status='PASS')) # SQLite primary key constraints rejected violations on insertion.
        checks.append(dict(name='REFERENTIAL_INTEGRITY',status='PASS' if not foreign_errors else 'FAIL',violations=len(foreign_errors)))
        checks.append(dict(name='TYPE_CONVERSIONS',status='PASS' if not conversion_errors else 'FAIL',errors=conversion_errors))
        for invariant in plan.get('business_invariants',[]):
            status='NOT_RUN'; details='This invariant kind is not supported by the local SQLite synthetic verifier.'
            kind=invariant['kind']; table=invariant['table']; col=invariant.get('column')
            column_mapping=next((m for m in maps if m['source_table'].casefold()==table.casefold() and m['source_column'].casefold()==str(col).casefold()),None)
            target_column=column_mapping['target_column'] if column_mapping else col
            if kind=='ROW_COUNT_EQUAL': status='PASS' if source_counts.get(table,0)==target_counts.get(table,0) else 'FAIL';details='Source and target row counts compared.'
            elif kind=='UNIQUE':
                tbl=table_by_source.get(table.casefold())
                if tbl and target_column:
                    dup=db.execute('SELECT COUNT(*) FROM (SELECT '+_q(target_column)+' FROM '+_q('tgt__'+tbl['name'])+' GROUP BY '+_q(target_column)+' HAVING COUNT(*)>1)').fetchone()[0]
                    status='PASS' if dup==0 else 'FAIL';details=dict(duplicate_values=dup)
            elif kind=='NOT_NULL':
                tbl=table_by_source.get(table.casefold())
                if tbl and target_column:
                    nulls=db.execute('SELECT COUNT(*) FROM '+_q('tgt__'+tbl['name'])+' WHERE '+_q(target_column)+' IS NULL').fetchone()[0]
                    status='PASS' if nulls==0 else 'FAIL';details=dict(null_values=nulls)
            elif kind=='FOREIGN_KEY_VALID': status='PASS' if not foreign_errors else 'FAIL';details=dict(violations=len(foreign_errors))
            checks.append(dict(name=invariant['name'],kind=kind,status=status,details=details))
        failed=any(x['status']=='FAIL' for x in checks)
        not_run=any(x['status']=='NOT_RUN' for x in checks)
        counts=dict(source=source_counts,target=target_counts)
        checks_hash=hashlib.sha256(json.dumps(checks,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return dict(state='FAIL' if failed else 'INCONCLUSIVE' if not_run else 'PASS',
            environment='EPHEMERAL_SQLITE_MEMORY',data_classification='SYNTHETIC',database_url_persisted=False,
            raw_fixture_persisted=False,counts=counts,checks=checks,result_sha256=checks_hash,
            recovery=dict(state='DISCARDED_WITH_PROCESS_MEMORY',backup_restore_tested=False),
            limitations=['This validates only the synthetic fixture and the supported local SQLite type/constraint checks.',
                          'It does not validate the application database engine (PostgreSQL or other), production-scale behavior, deployment cutover or backup restoration.'])
    except sqlite3.IntegrityError as exc:
        db.rollback()
        return dict(state='FAIL',environment='EPHEMERAL_SQLITE_MEMORY',data_classification='SYNTHETIC',
            database_url_persisted=False,raw_fixture_persisted=False,checks=[dict(name='DATABASE_CONSTRAINTS',status='FAIL',code='KEY_OR_RELATIONSHIP_CONSTRAINT_FAILED')],
            result_sha256=hashlib.sha256(b'KEY_OR_RELATIONSHIP_CONSTRAINT_FAILED').hexdigest(),
            recovery=dict(state='DISCARDED_WITH_PROCESS_MEMORY',backup_restore_tested=False),
            limitations=['The ephemeral SQLite database was rolled back and discarded; no source or target service was contacted.'])
    finally:
        db.close()
