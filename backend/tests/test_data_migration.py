from app.transformation.data_discovery import discover, propose_target
from app.transformation.migration_test_runner import execute


def test_discovery_finds_schema_access_paths_ownership_and_proposed_target():
    source='''CREATE TABLE customer (id BIGINT PRIMARY KEY, name VARCHAR(120) NOT NULL);\n'''
    java='''package com.example.customer;\nimport org.springframework.data.jpa.repository.JpaRepository;\npublic interface CustomerRepository extends JpaRepository<Customer, Long> {\n  Customer findById(Long id);\n  Customer save(Customer customer);\n}\n'''
    files={'src/main/resources/db/migration/V1__customer.sql':dict(content=source,sha256='a'*64),
        'src/main/java/com/example/customer/CustomerRepository.java':dict(content=java,sha256='b'*64)}
    analysis={'classes':[dict(id='com.example.customer.CustomerRepository',package_name='com.example.customer',domain_id='domain-customer')],
        'domains':[dict(id='domain-customer',name='Customer')], 'edges':[]}
    result=discover(files,full_source_snapshot=True,analysis=analysis)
    assert result['entities'][0]['name']=='customer'
    assert result['entities'][0]['primary_key']==['id']
    assert {x['operation'] for x in result['access_paths']}=={'READ','WRITE'}
    claim=result['ownership_map'][0]
    assert claim['candidate_domain_ids']==['domain-customer'] and claim['state']=='INFERRED'
    proposal=propose_target(result,analysis['domains'],'SQLITE_TEST')
    assert proposal['target_schema_state']=='PROPOSED'
    assert proposal['target_schema'][0]['source_resource']=='customer'
    assert proposal['mappings'][0]['state']=='INFERRED'
    assert proposal['execution_eligible'] is False


def test_unknown_source_schema_returns_smallest_discovery_question_and_still_proposes_target():
    result=discover({'src/App.java':dict(content='class App {}',sha256='c'*64)},full_source_snapshot=False,analysis={'classes':[]})
    proposal=propose_target(result,[])
    assert result['source_state']=='PARTIAL'
    assert result['questions'][0]['minimum_input']
    assert proposal['target_schema_state']=='PROPOSED'
    assert proposal['target_schema'][0]['state']=='PROPOSED_EMPTY'
    assert proposal['execution_eligible'] is False


def test_shared_cross_domain_data_access_stays_unresolved():
    files={'db/schema.sql':dict(content='CREATE TABLE customer (id BIGINT PRIMARY KEY);',sha256='a'*64),
        'src/a/CustomerReader.java':dict(content='package a; class CustomerReader { @Query("select c from customer c") Object read(){ return null; } }',sha256='b'*64),
        'src/b/CustomerWriter.java':dict(content='package b; class CustomerWriter { @Query("update customer set id=1") void write(){} }',sha256='c'*64)}
    analysis={'classes':[dict(package_name='a',domain_id='domain-a'),dict(package_name='b',domain_id='domain-b')]}
    result=discover(files,full_source_snapshot=True,analysis=analysis)
    claim=result['ownership_map'][0]
    assert claim['state']=='UNRESOLVED' and claim['shared_access']
    assert claim['candidate_domain_ids']==['domain-a','domain-b']
    assert any(item['kind']=='SHARED_DATA_ACCESS_REVIEW_REQUIRED' for item in result['unresolved'])
    assert result['questions'] and 'customer' in result['questions'][0]['question']


def test_synthetic_runner_checks_copy_and_rejects_bad_conversion_without_retaining_rows():
    plan=dict(source_schema=[dict(name='customer',columns=[dict(name='id',data_type='INT64',nullable=False),
        dict(name='name',data_type='STRING',nullable=False)],primary_key=['id'],foreign_keys=[])],
        target_schema=[dict(name='customer',source_resource='customer',columns=[dict(name='id',data_type='INT64',nullable=False),
        dict(name='name',data_type='STRING',nullable=False)],primary_key=['id'],foreign_keys=[])],
        mappings=[dict(source_table='customer',source_column='id',target_table='customer',target_column='id',target_type='INT64'),
        dict(source_table='customer',source_column='name',target_table='customer',target_column='name',target_type='STRING')],business_invariants=[])
    success=execute(plan,{'customer':[{'id':1,'name':'Synthetic row'}]})
    assert success['state']=='PASS'
    assert success['counts']==dict(source={'customer':1},target={'customer':1})
    assert success['raw_fixture_persisted'] is False
    failed=execute(plan,{'customer':[{'id':'bad-id','name':'Synthetic row'}]})
    assert failed['state']=='FAIL'
    assert failed['raw_fixture_persisted'] is False
    assert failed['recovery']['state']=='DISCARDED_WITH_PROCESS_MEMORY'


def test_synthetic_runner_checks_renamed_columns_keys_and_explicit_invariants():
    plan=dict(source_schema=[dict(name='customer',columns=[dict(name='id',data_type='INT64',nullable=False),
        dict(name='email',data_type='STRING',nullable=False)],primary_key=['id'],foreign_keys=[])],
        target_schema=[dict(name='customer_v2',source_resource='customer',columns=[dict(name='id',data_type='INT64',nullable=False),
        dict(name='email_address',data_type='STRING',nullable=False)],primary_key=['id'],foreign_keys=[])],
        mappings=[dict(source_table='customer',source_column='id',target_table='customer_v2',target_column='id',target_type='INT64'),
        dict(source_table='customer',source_column='email',target_table='customer_v2',target_column='email_address',target_type='STRING')],
        business_invariants=[dict(name='unique-email',kind='UNIQUE',table='customer',column='email'),
            dict(name='email-present',kind='NOT_NULL',table='customer',column='email')])
    valid=execute(plan,{'customer':[{'id':1,'email':'a@example.invalid'},{'id':2,'email':'b@example.invalid'}]})
    assert valid['state']=='PASS'
    assert [item['status'] for item in valid['checks'][-2:]]==['PASS','PASS']
    duplicate=execute(plan,{'customer':[{'id':1,'email':'same@example.invalid'},{'id':2,'email':'same@example.invalid'}]})
    assert duplicate['state']=='FAIL'
    assert duplicate['checks'][-2]['status']=='FAIL'
