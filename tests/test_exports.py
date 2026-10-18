import json
import sqlite3
from pathlib import Path

from collector.pipeline import parse_offline
from .test_parser import URL, sample_program


def test_offline_end_to_end(tmp_path: Path):
    text = tmp_path / 'race.txt'
    text.write_text(sample_program(),encoding='utf-8')
    dest = parse_offline(text,URL,tmp_path/'out',expected_horses=15)
    payload = json.loads((dest/'program.json').read_text(encoding='utf-8'))
    assert payload['races'][0]['qa']['entrant_count'] == 15
    assert payload['races'][0]['qa']['past_start_rows'] == 75
    assert (dest/'program.xlsx').stat().st_size > 3000
    assert (dest/'program.pdf').read_bytes().startswith(b'%PDF')
    db = sqlite3.connect(dest/'program.sqlite')
    assert db.execute('SELECT COUNT(*) FROM entrants').fetchone()[0] == 15
    assert db.execute('SELECT COUNT(*) FROM past_starts').fetchone()[0] == 75
    assert db.execute('SELECT horse_name FROM scratches').fetchone()[0] == 'Lesja Loke'
    db.close()


def test_mismatch_is_a_warning(tmp_path: Path):
    text=tmp_path/'race.txt'; text.write_text(sample_program(),encoding='utf-8')
    dest=parse_offline(text,URL,tmp_path/'out',expected_horses=16)
    doc=json.loads((dest/'program.json').read_text(encoding='utf-8'))['races'][0]
    assert 'EXPECTED_16_HORSES_FOUND_15' in doc['qa']['warnings']