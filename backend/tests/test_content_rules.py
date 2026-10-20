"""Content rules: banned filler phrases and prose that names nothing and counts nothing.

The repository scan fails on any new violation. The unit tests pin the behavior of the checker itself.
"""
from pathlib import Path

import pytest

from app.content.check import check_text, load_rules, scan

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rules()


def kinds(text, **kw):
    return [v.kind for v in check_text(text, 'x', 1, RULES, **kw)]


@pytest.mark.parametrize('phrase', ['leverage', 'seamless', 'robust', 'comprehensive', 'holistic', 'powerful',
    'cutting-edge', 'It is important to note', 'In today\'s world', 'delve', 'streamline', 'unlock', 'ensure that',
    'provides insights into', 'various', 'several'])
def test_every_banned_phrase_is_detected(phrase):
    assert 'BANNED' in kinds(f'The OwnerService class will {phrase} the 12 packages.')


def test_banned_phrase_is_detected_in_a_message_role():
    assert 'BANNED' in kinds('A robust failure for OwnerService.', role='message')


def test_generic_sentence_is_flagged_and_specific_sentence_is_not():
    assert kinds('This page shows the information that you need to know about the application today.') == ['NO_SPECIFIC']
    assert kinds('OwnerController depends on 3 repositories in package org.springframework.samples.petclinic.owner.') == []
    assert kinds('Readiness = sum of component × weight over the measured components, renormalised to 100.') == []


def test_not_measured_text_counts_as_specific():
    assert kinds('Runtime coverage is not measured here because no session is selected for this analysis.') == []


def test_questions_make_no_claim():
    assert kinds('How many classes and packages does the application have in total today?') == []


def test_short_text_is_not_checked_for_specificity():
    assert kinds('Run analysis') == []


def test_repository_text_passes_the_content_rules():
    violations = scan(ROOT)
    assert not violations, '\n'.join(v.render() for v in sorted(violations, key=lambda v: (v.file, v.line))[:40])
