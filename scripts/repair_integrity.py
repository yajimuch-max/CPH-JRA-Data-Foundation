"""Read-only checks that gate repaired JRA MASTER exports."""

import json
from collections import Counter

PERSON_FIELDS = {'jockey_name', 'jockey_id', 'trainer_name', 'trainer_id'}
PRESERVED = (
    'races', 'horses', 'results', 'win_odds', 'payouts', 'laps', 'corners',
    'pedigree', 'pedigree_receipts', 'official_track_daily',
    'official_track_pdf_receipts', 'official_html_receipts',
    'official_html_races', 'official_html_runners', 'official_html_revisions',
    'tasks', 'issues',
)
REFUND_TECHNICAL_TABLES = {
    'metadata', 'source_records', 'race_sources', 'revisions',
    'refund_receipts', 'host_budget',
}


def person_diff(old, new):
    """Allow only blank jockey or trainer fields to be filled."""
    if old.keys() != new.keys():
        raise ValueError('RUNNER_SET_CHANGED')
    counts = Counter()
    for key, (horse_id, old_fields) in old.items():
        new_id, new_fields = new[key]
        if horse_id != new_id:
            raise ValueError('HORSE_ID_CHANGED')
        for column in old_fields.keys() | new_fields.keys():
            previous = old_fields.get(column)
            replacement = new_fields.get(column)
            if previous == replacement:
                continue
            if column not in PERSON_FIELDS or (previous is not None and str(previous).strip()):
                raise ValueError('NONMISSING_OR_NONPERSON_FIELD_CHANGED')
            if replacement is None or not str(replacement).strip():
                raise ValueError('INVALID_PERSON_REPLACEMENT')
            counts[column] += 1
    return dict(counts)


def runner_payloads(connection):
    return {
        (race_id, number): (horse_id, json.loads(payload))
        for race_id, number, horse_id, payload in connection.execute(
            'SELECT race_id, horse_number, horse_id, payload_json FROM runners'
        )
    }


def table_names(connection):
    return {
        name for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        if not name.startswith('sqlite_')
    }


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def table_columns(connection, table):
    return [row[1] for row in connection.execute(f'PRAGMA table_info({quote_identifier(table)})')]


def table_rows(connection, table, columns, *, exclude_refunds=False):
    order = ', '.join(map(quote_identifier, columns))
    query = f'SELECT * FROM {quote_identifier(table)}'
    if exclude_refunds:
        query += " WHERE bet_type <> 'REFUND'"
    return [tuple(row) for row in connection.execute(f'{query} ORDER BY {order}')]


def compare_person_repair(before, after):
    """Check original evidence before reusing it for a person-only export."""
    checked = {}
    existing = table_names(before)
    for table in PRESERVED:
        if table not in existing:
            continue
        columns = table_columns(before, table)
        if columns != table_columns(after, table):
            raise ValueError('TABLE_SCHEMA_CHANGED:' + table)
        old_rows = table_rows(before, table, columns)
        if old_rows != table_rows(after, table, columns):
            raise ValueError('NONPERSON_TABLE_CHANGED:' + table)
        checked[table] = len(old_rows)
    return {
        'exact_preserved_tables': checked,
        'person_fields_changed': person_diff(runner_payloads(before), runner_payloads(after)),
    }


def preserve(before, after, baseline_comparison=False):
    """Check non-refund data against the prior state or pinned baseline."""
    original_tables = table_names(before)
    if not original_tables.issubset(table_names(after)):
        raise ValueError('EXISTING_TABLE_REMOVED')
    tables = PRESERVED if baseline_comparison else original_tables - REFUND_TECHNICAL_TABLES
    checked = []
    for table in sorted(tables):
        if table not in original_tables or (baseline_comparison and table == 'runners'):
            continue
        columns = table_columns(before, table)
        if columns != table_columns(after, table):
            raise ValueError('PRESERVATION_FAILED:' + table)
        exclude_refunds = table == 'payouts'
        if table_rows(before, table, columns, exclude_refunds=exclude_refunds) != table_rows(
            after, table, columns, exclude_refunds=exclude_refunds
        ):
            raise ValueError('PRESERVATION_FAILED:' + table)
        checked.append(table)
    if baseline_comparison:
        person_diff(runner_payloads(before), runner_payloads(after))
    return checked
