"""Checkpoint official refunds without changing learning data; certify only full coverage."""
import argparse,json,sqlite3,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'engine'),str(ROOT/'scripts')]
from historical_person_export import baseline,person_diff,rows,PRESERVED
TECHNICAL={'metadata','source_records','race_sources','revisions','refund_receipts','host_budget'}

def tables(c):return {r[0] for r in c.execute("select name from sqlite_master where type='table'") if not r[0].startswith('sqlite_')}
def table_rows(c,table,where=''):
 cols=[r[1] for r in c.execute('pragma table_info("'+table.replace('"','""')+'")')]
 return cols,[tuple(r) for r in c.execute('select * from "'+table.replace('"','""')+'" '+where+' order by '+','.join('"'+col+'"' for col in cols))]
def unchanged(a,b,table,where=''):
 if table_rows(a,table,where)!=table_rows(b,table,where):raise ValueError('PRESERVATION_FAILED:'+table)
def preserve(a,b,baseline_comparison=False):
 if not tables(a).issubset(tables(b)):raise ValueError('EXISTING_TABLE_REMOVED')
 checked=[]
 for t in sorted(PRESERVED if baseline_comparison else tables(a)-TECHNICAL):
  if t not in tables(a):continue
  if t=='payouts':unchanged(a,b,t,"where bet_type<>'REFUND'")
  elif baseline_comparison and t=='runners':continue
  else:unchanged(a,b,t)
  checked.append(t)
 if baseline_comparison:person_diff(rows(a),rows(b))
 if not tables(a).issubset(tables(b)):raise ValueError('EXISTING_TABLE_REMOVED')
 return checked

def main():
 p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--db',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('delivery'));p.add_argument('--cache',type=Path,default=Path('jra_refund_cache'));p.add_argument('--max-pages',type=int,default=4000);a=p.parse_args()
 if not 2010<=a.year<=2025 or not 1<=a.max_pages<=4000:raise ValueError('INVALID_RANGE')
 raw,manifest,original_audit=baseline(a.source,a.year);a.output.mkdir(parents=True,exist_ok=True);a.db.parent.mkdir(parents=True,exist_ok=True)
 if not a.db.exists():a.db.write_bytes(raw)
 original=sqlite3.connect(':memory:');original.deserialize(raw)
 before=sqlite3.connect(':memory:');current=sqlite3.connect(a.db);current.backup(before);current.close()
 # Reject a restored state that already diverged beyond person/refund repair.
 baseline_checked=preserve(original,before,True)
 from jra_master.store import Store
 from jra_master.network import Client
 from jra_master.refunds import run
 s=Store(a.db)
 try:
  report=run(s,Client(s,a.cache/'raw',budget_seconds=10800),a.year,a.cache,max_pages=a.max_pages,budget_seconds=10800)
  kept=preserve(before,s.c)
  if s.c.execute('pragma integrity_check').fetchone()[0]!='ok' or s.c.execute('pragma foreign_key_check').fetchall():raise ValueError('INVALID_REPAIRED_DB')
  report.update(exact_preserved_tables=kept,baseline_checked_tables=baseline_checked,source_master_sha256=manifest['master_sha256'],learning_tables_unchanged=True)
 finally:s.c.close();original.close();before.close()
 (a.output/f'refund_audit_{a.year}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 if report['status']!='PASS' or report['errors']:
  print('REFUND_CHECKPOINT_INCOMPLETE',json.dumps(report,ensure_ascii=False),flush=True);return 2
 from jra_master.unified_export import export_master
 audit=export_master(a.year,a.db,a.output,original_audit['stages'])
 if audit['status']!='CERTIFIED':raise ValueError('EXPORT_NOT_CERTIFIED:'+','.join(audit['blockers']))
 print('REFUND_REPAIRED_MASTER_CERTIFIED',a.year,flush=True);return 0
if __name__=='__main__':sys.exit(main())
