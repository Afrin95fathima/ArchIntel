"""Offline detectors; never verify discovered credentials against any service."""
import re
import unicodedata
from detect_secrets.plugins.keyword import KeywordDetector
from detect_secrets.plugins.private_key import PrivateKeyDetector
from detect_secrets.plugins.aws import AWSKeyDetector
from detect_secrets.plugins.jwt import JwtTokenDetector
from detect_secrets.plugins.basic_auth import BasicAuthDetector
from detect_secrets.plugins.high_entropy_strings import Base64HighEntropyString, HexHighEntropyString, HighEntropyStringsPlugin

VERSION='local-filter-1'


class FilterDenied(ValueError):
    pass


# analyze_string is offline; analyze_line can invoke upstream verification filters.
DETECTORS=(KeywordDetector(),PrivateKeyDetector(),AWSKeyDetector(),JwtTokenDetector(),
           BasicAuthDetector(),Base64HighEntropyString(4.5),HexHighEntropyString(3.5))
PII=[('EMAIL',re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I)),
     ('GOVERNMENT_ID',re.compile(r'\b\d{3}-\d{2}-\d{4}\b')),
     ('PAYMENT_NUMBER',re.compile(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)')),
     ('PHONE',re.compile(r'(?<!\w)\+\d[\d ()-]{8,18}\d'))]
INJECTION=re.compile(r'(ignore|override|disregard)\s+(all\s+|the\s+)?(previous|system|developer)\s+(instructions|rules)|<\|(?:im_start|system)|\[INST\]|exfiltrat|reveal\s+(the\s+)?(system prompt|secrets)',re.I)
CREDENTIAL=re.compile(r'(?i)(?:bearer\s+[A-Za-z0-9._~+/-]{12,}|(?:api[_-]?key|password|secret|token)\s*[:=]\s*["\']?[^\s"\',;}{]{6,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')


def has_secret(line):
    for detector in DETECTORS:
        for match in detector.analyze_string(line):
            # Upstream entropy plugins yield candidates in analyze_string;
            # apply their entropy calculation without invoking network verification.
            if isinstance(detector,HighEntropyStringsPlugin):
                if detector.calculate_shannon_entropy(match)<=detector.entropy_limit:
                    continue
            return True
    return False


def sanitize(value, mode='REDACT'):
    value=unicodedata.normalize('NFKC',value)
    if any(unicodedata.category(c)=='Cf' for c in value):
        raise FilterDenied('INVISIBLE_CONTROL')
    if INJECTION.search(value):
        raise FilterDenied('PROMPT_INJECTION')
    categories=set()
    # Secrets always block; PII may be redacted. No raw matches leave this function.
    for line in value.splitlines() or [value]:
        if CREDENTIAL.search(line) or has_secret(line):
            raise FilterDenied('SECRET_DETECTED')
    for category,pattern in PII:
        if pattern.search(value):
            if mode=='BLOCK':raise FilterDenied('SENSITIVE_DATA')
            value=pattern.sub('[REDACTED_'+category+']',value);categories.add(category)
    return value,sorted(categories)
