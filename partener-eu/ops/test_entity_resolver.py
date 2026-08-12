#!/usr/bin/env python3
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).with_name('entity_resolver_service.py')
spec = importlib.util.spec_from_file_location('entity_resolver_service', MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_clean_cui():
    assert mod.clean_cui('RO 2541894') == '2541894'


def test_source_priority_and_conflict_preservation():
    a = {
        'cui': '12345678', 'name': 'SC EXEMPLU SRL', 'county': 'Vâlcea',
        '_provider': 'ANAF', '_tier': 'A', 'confidence': 0.98,
        'sourceFacts': [{'label': 'ANAF', 'tier': 'A'}]
    }
    b = {
        'cui': '12345678', 'name': 'EXEMPLU SRL', 'county': 'Argeș',
        '_provider': 'ALT', '_tier': 'B', 'confidence': 0.80,
        'sourceFacts': [{'label': 'ALT', 'tier': 'B'}]
    }
    out = mod.merge_records([b, a])
    assert out['name'] == 'SC EXEMPLU SRL'
    assert out['county'] == 'Vâlcea'
    assert len(out['conflicts']) == 2
    assert out['confidence'] == 0.98


def test_classify_uat_and_company():
    uat = mod.classify_entity({'name': 'Primăria Orașului Brezoi'})
    assert uat['type'] == 'municipality'
    assert uat['entityClass'] == 'UAT'
    company = mod.classify_entity({'name': 'SC EXEMPLU SRL'})
    assert company['type'] == 'enterprise'
    assert company['entityClass'] == 'COMPANY'


def main():
    test_clean_cui()
    test_source_priority_and_conflict_preservation()
    test_classify_uat_and_company()
    print('PASS entity_resolver_service')


if __name__ == '__main__':
    main()
