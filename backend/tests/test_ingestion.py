import zipfile
import pytest
from app.config import Settings
from app.services.ingestion import validate_archive,validate_project_zip,ArtifactError,remove_job


@pytest.mark.parametrize('name',['../evil.class','/absolute.class','C:/escape.class','a/../../bad.class','a\\..\\bad.class'])
def test_unsafe_paths_rejected(tmp_path,name):
    target=tmp_path/'bad.jar'
    with zipfile.ZipFile(target,'w') as z:z.writestr(name,b'bad')
    with pytest.raises(ArtifactError):validate_archive(target,Settings(_env_file=None))


def test_no_classes_and_entry_limits(tmp_path):
    target=tmp_path/'bad.jar'
    with zipfile.ZipFile(target,'w') as z:z.writestr('README.txt','x')
    with pytest.raises(ArtifactError):validate_archive(target,Settings(_env_file=None))
    with pytest.raises(ArtifactError):validate_archive(target,Settings(_env_file=None,max_archive_entries=0))


def test_duplicate_class_paths_rejected(tmp_path):
    target=tmp_path/'bad.jar'
    with zipfile.ZipFile(target,'w') as z:
        z.writestr('a/A.class',b'\xca\xfe\xba\xbe')
        z.writestr('BOOT-INF/classes/a/A.class',b'\xca\xfe\xba\xbe')
    with pytest.raises(ArtifactError):validate_archive(target,Settings(_env_file=None))


def test_cleanup_stays_inside_owned_root(tmp_path):
    with pytest.raises(ValueError):remove_job(tmp_path,tmp_path)
    with pytest.raises(ValueError):remove_job(tmp_path.parent,tmp_path)
    child=tmp_path/'job';child.mkdir()
    remove_job(child,tmp_path)
    assert not child.exists()


def test_war_extraction_and_bad_magic(tmp_path):
    target=tmp_path/'sample.war'
    with zipfile.ZipFile(target,'w') as z:z.writestr('WEB-INF/classes/a/A.class',b'\xca\xfe\xba\xbe')
    out=tmp_path/'out';out.mkdir()
    validate_archive(target,Settings(_env_file=None),out)
    assert (out/'a/A.class').exists()
    with zipfile.ZipFile(target,'w') as z:z.writestr('a/B.class',b'not bytecode')
    with pytest.raises(ArtifactError):validate_archive(target,Settings(_env_file=None),out)


def test_project_zip_collects_compiled_module_outputs_and_deduplicates_identical_classes(tmp_path):
    bundle=tmp_path/'project.zip'
    class_bytes=b'\xca\xfe\xba\xbecompiled-class'
    with zipfile.ZipFile(bundle,'w') as z:
        z.writestr('concord/server/target/classes/org/example/Server.class',class_bytes)
        z.writestr('concord/common/target/classes/org/example/Server.class',class_bytes)
        z.writestr('concord/server/src/main/java/org/example/Server.java','package org.example;')
    out=tmp_path/'classes';out.mkdir()
    manifest=validate_project_zip(bundle,Settings(_env_file=None),out)
    assert manifest['packaging']=='JAVA_PROJECT_ZIP'
    assert manifest['class_files']==1
    assert manifest['duplicate_identical_classes']==1
    assert (out/'org/example/Server.class').read_bytes()==class_bytes


def test_project_zip_scans_module_jars_and_skips_bundled_dependency_classes(tmp_path):
    bundle=tmp_path/'project.zip'
    module=tmp_path/'module.jar'
    with zipfile.ZipFile(module,'w') as z:
        z.writestr('org/example/Service.class',b'\xca\xfe\xba\xbeapp')
        z.writestr('lib/thirdparty/Library.class',b'\xca\xfe\xba\xbethirdparty')
    with zipfile.ZipFile(bundle,'w') as z:
        z.write(module,'service/target/service.jar')
    out=tmp_path/'classes';out.mkdir()
    manifest=validate_project_zip(bundle,Settings(_env_file=None),out)
    assert manifest['class_files']==1
    assert manifest['nested_archives']==1
    assert (out/'org/example/Service.class').exists()
    assert not (out/'lib/thirdparty/Library.class').exists()


def test_project_zip_rejects_source_only_and_reports_conflicting_duplicate_classes(tmp_path):
    bundle=tmp_path/'project.zip'
    with zipfile.ZipFile(bundle,'w') as z:z.writestr('app/src/main/java/A.java','class A {}')
    with pytest.raises(ArtifactError,match='source-only ZIPs are not yet supported'):
        validate_project_zip(bundle,Settings(_env_file=None))
    with zipfile.ZipFile(bundle,'w') as z:
        z.writestr('a/target/classes/p/A.class',b'\xca\xfe\xba\xbeone')
        z.writestr('b/target/classes/p/A.class',b'\xca\xfe\xba\xbetwo')
    out=tmp_path/'classes';out.mkdir()
    manifest=validate_project_zip(bundle,Settings(_env_file=None),out)
    assert manifest['class_files']==1
    assert manifest['conflicting_duplicate_classes']==1
    assert manifest['conflicting_duplicate_examples'][0]['selected'].startswith('a/')
    assert manifest['conflicting_duplicate_examples'][0]['ignored'].startswith('b/')
    assert (out/'p/A.class').read_bytes()==b'\xca\xfe\xba\xbeone'
