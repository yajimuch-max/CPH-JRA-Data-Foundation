import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import current_refund_repair as current
from jra_master.html_first import schema
from jra_master.model import ParsedRace, RaceEntry, RaceResult
from jra_master.store import Store, encode

RID = '2026-01-05-中山-01'
URL = 'https://www.jra.go.jp/JRADB/accessS.html?CNAME=TEST'


class CurrentRefundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'MASTER.sqlite3'
        self.audit = self.root / 'update.json'
        self.output = self.root / 'delivery'
        self.cache = self.root / 'cache'
        s = Store(self.db)
        s.meta('year', 2026)
        schema(s.c)
        with s.c:
            s.c.execute('insert into races values(?,?,?,?,?,?)', (RID, '2026-01-05', '中山', 1, 'FLAT', encode({'surface': '芝', 'distance_m': 1600})))
            s.c.execute("insert into horses values('H','馬')")
            s.c.execute('insert into runners values(?,?,?,?)', (RID, 1, 'H', encode({'jockey_name': '騎手', 'trainer_name': '調教師'})))
            s.c.execute('insert into results values(?,?,?)', (RID, 1, encode({'finish_status': '除外'})))
            s.c.execute('insert into win_odds values(?,?,?,?,?,?)', (RID, 1, None, 'EXCLUDED', None, '{}'))
            s.c.execute('insert into payouts values(?,?,?,?)', (RID, 'WIN', 1, encode({'payout_yen': 480})))
            s.c.execute('insert into laps values(?,?,?)', (RID, 1, encode({'lap_time_seconds': 12.0})))
            s.c.execute("insert into pedigree_receipts values('H','SOURCE',4,'PASS')")
            s.c.execute('insert into official_html_receipts values(?,?,?,?,?,?,?)', (RID, URL, 'a'*64, 'TEST', 'PASS', None, 'NOW'))
            s.c.execute('insert into official_html_races values(?,?,?,?,?,?,?,?,?)', (RID, '晴', '良', '3歳', '未勝利', URL, 'a'*64, 'POST_EVENT', 'NOW'))
        self.stages = {'core': {'status': 'PASS'}, 'track': {'status': 'PARTIAL'}}
        self.prior = current.audit_source(s.c, 2026, self.stages)
        self.audit.write_text(json.dumps(self.prior))
        s.c.close()
        self.parsed = ParsedRace('2026-01-05', '中山', '1回中山1日', 1, '未勝利', '芝', 1600, '芝右', '10:00', '晴', '良', None,
                                 [RaceEntry(1, 1, 'H', '馬', '牡3', 57., None, '騎手', None, '調教師', 500, None)],
                                 [RaceResult(1, '除外', None, None, None)])

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, extra=None):
        html = '<html><p>返還馬番1番</p></html>'.encode('cp932')
        with patch('jra_master.person_repair.result_url', return_value=URL), \
             patch('jra_master.refunds.parse_result', return_value=self.parsed), \
             patch.object(current.Client, 'request', return_value=(html, None, None)):
            if extra:
                with extra:
                    return current.repair(self.db, self.audit, self.output, self.cache)
            return current.repair(self.db, self.audit, self.output, self.cache)

    def test_real_repair_preserves_data_and_keeps_pdf_pending_provisional(self):
        self.assertEqual(self.execute(), 0)
        with zipfile.ZipFile(self.output / '2026_JRA_WEEKLY_SNAPSHOT.zip') as z:
            manifest = json.loads(z.read('manifest.json'))
            audit = json.loads(z.read('AUDIT.json'))
        self.assertEqual(manifest['status'], 'PROVISIONAL_NOT_CERTIFIED')
        self.assertEqual(audit['blockers'], ['OFFICIAL_MEASUREMENTS_NOT_COMPLETE'])
        self.assertEqual(audit['refund_coverage']['verified_races'], 1)
        self.assertFalse((self.output / '2026_JRA_MASTER.zip').exists())
        report = json.loads((self.output / 'refund_audit_2026.json').read_text())
        self.assertTrue(report['learning_tables_unchanged'])
        self.assertIn('runners', report['exact_preserved_tables'])

    def test_repeated_repair_uses_checkpoint_without_duplicates(self):
        self.execute()
        with sqlite3.connect(self.db) as c:
            self.audit.write_text(json.dumps(current.audit_source(c, 2026, self.stages)))
        self.assertEqual(self.execute(), 0)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("select count(*) from payouts where bet_type='REFUND'").fetchone()[0], 1)
        self.assertEqual(json.loads((self.output / 'refund_audit_2026.json').read_text())['checked_this_run'], 0)

    def test_unfinished_checkpoint_never_exports(self):
        with patch.object(current, 'run', return_value={'status': 'NOT_FULLY_VERIFIED', 'errors': []}):
            self.assertEqual(current.repair(self.db, self.audit, self.output, self.cache), 2)
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_person_mutation_blocks_export(self):
        real_run = current.run
        def bad_run(store, *args, **kwargs):
            report = real_run(store, *args, **kwargs)
            with store.c:
                store.c.execute("update runners set payload_json='{}'")
            return report
        with self.assertRaisesRegex(ValueError, 'PRESERVATION_FAILED:runners'):
            self.execute(patch.object(current, 'run', side_effect=bad_run))
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_wrong_year_rejected_before_network(self):
        self.prior['year'] = 2025
        self.audit.write_text(json.dumps(self.prior))
        with self.assertRaisesRegex(ValueError, 'CURRENT_UPDATE_AUDIT_REQUIRED'):
            self.execute()

    def test_stale_update_audit_rejected(self):
        self.prior['source_races'] += 1
        self.audit.write_text(json.dumps(self.prior))
        with self.assertRaisesRegex(ValueError, 'STATE_UPDATE_AUDIT_MISMATCH'):
            self.execute()

    def test_missing_state_is_not_created(self):
        self.db.unlink()
        with self.assertRaisesRegex(ValueError, 'CURRENT_STATE_REQUIRED'):
            self.execute()
        self.assertFalse(self.db.exists())

    def test_non_pdf_core_defect_is_not_hidden(self):
        with sqlite3.connect(self.db) as c:
            c.execute('delete from results')
            c.commit()
            self.audit.write_text(json.dumps(current.audit_source(c, 2026, self.stages)))
        with self.assertRaisesRegex(ValueError, 'BASE_STATE_NOT_READY'):
            self.execute()


if __name__ == '__main__':
    unittest.main()
