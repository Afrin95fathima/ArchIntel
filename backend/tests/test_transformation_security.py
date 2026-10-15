import pytest
from app.transformation.security import parse_report
from app.transformation.sandbox import SandboxError


def report(finding='', errors='0', missing='0', count='0'):
    return (f'<BugCollection version="4.10.4">{finding}<Errors errors="{errors}" missingClasses="{missing}"/>'
            f'<FindBugsSummary total_classes="1" total_bugs="{count}"/></BugCollection>').encode()


def test_security_findings_and_incomplete_reports_cannot_pass():
    assert parse_report(report())['state']=='PASS'
    finding='<BugInstance type="WEAK_MESSAGE_DIGEST_MD5" category="SECURITY" priority="2"><Class classname="sample.Unsafe"/></BugInstance>'
    result=parse_report(report(finding, count='1'))
    assert result['state']=='FAIL' and result['findings'][0]['rule']=='WEAK_MESSAGE_DIGEST_MD5'
    assert parse_report(report(errors='1'))['state']=='INCONCLUSIVE'
    assert parse_report(report(missing='1'))['state']=='INCONCLUSIVE'


@pytest.mark.parametrize('raw', [b'',b'<BugCollection/>',b'<!DOCTYPE x><BugCollection/>',
    report().replace(b'4.10.4',b'unknown'), report().replace(b'total_classes="1"',b'total_classes="0"'),
    report(count='1')])
def test_invalid_security_reports_fail_closed(raw):
    with pytest.raises(SandboxError): parse_report(raw)
