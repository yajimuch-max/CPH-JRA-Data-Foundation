"""Reconcile 2026 refunds on the current update state, then export honestly."""
import argparse
import hashlib
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'engine'), str(ROOT / 'scripts')]
from refund_repair_export import preserve
from jra_master.store import Store
from jra_master.network import Client
from jra_master.refunds import run, audit as refund_audit
from jra_master.unified_export import audit_source, export_master


def repair(db, stage_audit, output, cache, max_pages=4000):
    if not db.is_file():
        raise ValueError('CURRENT_STATE_REQUIRED')
    if not 1 <= max_pages <= 4000:
        raise ValueError('INVALID_PAGE_LIMIT')
    prior = json.loads(stage_audit.read_text())
    if prior.get('year') != 2026 or not isinstance(prior.get('stages'), dict):
        raise ValueError('CURRENT_UPDATE_AUDIT_REQUIRED')
    stages = prior['stages']
    if stages.get('core', {}).get('status') != 'PASS':
        raise ValueError('CORE_UPDATE_NOT_COMPLETE')
    before = sqlite3.connect(':memory:')
    source = sqlite3.connect('file:' + str(db.resolve()) + '?mode=ro', uri=True)
    try:
        source.backup(before)
    finally:
        source.close()
    output.mkdir(parents=True, exist_ok=True)
    try:
        initial = audit_source(before, 2026, stages)
        if (initial['core_counts'] != prior.get('core_counts') or
                initial['source_races'] != prior.get('source_races')):
            raise ValueError('STATE_UPDATE_AUDIT_MISMATCH')
        # A resumed refund checkpoint may still be incomplete. All other core
        # defects block this repair; missing official PDF values stay explicit.
        allowed = {'OFFICIAL_MEASUREMENTS_NOT_COMPLETE', 'REFUND_HTML_NOT_ALL_VERIFIED'}
        if set(initial['blockers']) - allowed:
            raise ValueError('BASE_STATE_NOT_READY:' + ','.join(initial['blockers']))
        store = Store(db)
        try:
            report = run(store, Client(store, cache / 'raw', budget_seconds=10800),
                         2026, cache, max_pages=max_pages, budget_seconds=10800)
            report['exact_preserved_tables'] = preserve(before, store.c)
            report['learning_tables_unchanged'] = True
            report['source_races'] = initial['source_races']
            if (store.c.execute('pragma integrity_check').fetchone()[0] != 'ok' or
                    store.c.execute('pragma foreign_key_check').fetchall()):
                raise ValueError('INVALID_REPAIRED_DB')
            coverage = refund_audit(store.c, 2026)
        finally:
            store.c.close()
    finally:
        before.close()
    (output / 'refund_audit_2026.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if report['status'] != 'PASS' or report['errors'] or coverage['status'] != 'PASS':
        print('CURRENT_REFUND_CHECKPOINT_INCOMPLETE', json.dumps(report, ensure_ascii=False))
        return 2
    result = export_master(2026, db, output, stages)
    if set(result['blockers']) - {'OFFICIAL_MEASUREMENTS_NOT_COMPLETE'}:
        raise ValueError('CURRENT_EXPORT_BLOCKED:' + ','.join(result['blockers']))
    name = '2026_JRA_MASTER.zip' if result['status'] == 'CERTIFIED' else '2026_JRA_WEEKLY_SNAPSHOT.zip'
    with zipfile.ZipFile(output / name) as archive:
        if archive.testzip():
            raise ValueError('EXPORTED_ZIP_CORRUPT')
        manifest = json.loads(archive.read('manifest.json'))
        audit = json.loads(archive.read('AUDIT.json'))
        if (manifest['year'] != 2026 or
                hashlib.sha256(archive.read('MASTER.sqlite3')).hexdigest() != manifest['master_sha256'] or
                audit['refund_coverage']['status'] != 'PASS'):
            raise ValueError('EXPORTED_SNAPSHOT_INVALID')
    print('CURRENT_REFUND_COMPLETE', name, manifest['status'], result['refund_coverage'])
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--stage-audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('delivery'))
    parser.add_argument('--cache', type=Path, default=Path('jra_refund_cache'))
    parser.add_argument('--max-pages', type=int, default=4000)
    args = parser.parse_args()
    return repair(args.db, args.stage_audit, args.output, args.cache, args.max_pages)


if __name__ == '__main__':
    sys.exit(main())
