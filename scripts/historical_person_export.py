"""Verify a person-only repair against a pinned original, then audit/export it."""
import argparse,collections,hashlib,json,sqlite3,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
ALLOWED={'jockey_name','jockey_id','trainer_name','trainer_id'}
PRESERVED=('races','horses','results','win_odds','payouts','laps','corners','pedigree','pedigree_receipts','official_track_daily','official_track_pdf_receipts','official_html_receipts','official_html_races','official_html_runners','official_html_revisions','tasks','issues')

def person_diff(old,new):
 if old.keys()!=new.keys():raise ValueError('RUNNER_SET_CHANGED')
 counts=collections.Counter()
 for key,(hid,x) in old.items():
  newhid,y=new[key]
  if hid!=newhid:raise ValueError('HORSE_ID_CHANGED')
  for col in x.keys()|y.keys():
   if x.get(col)==y.get(col):continue
   if col not in ALLOWED or x.get(col) is not None and str(x[col]).strip():raise ValueError('NONMISSING_OR_NONPERSON_FIELD_CHANGED')
   if y.get(col) is None or not str(y[col]).strip():raise ValueError('INVALID_PERSON_REPLACEMENT')
   counts[col]+=1
 return dict(counts)

def rows(c):
 return {(rid,no):(hid,json.loads(raw)) for rid,no,hid,raw in c.execute('select race_id,horse_number,horse_id,payload_json from runners')}

def compare(a,b):
 tables={r[0] for r in a.execute("select name from sqlite_master where type='table'")};checked={}
 for table in PRESERVED:
  if table not in tables:continue
  cols=[r[1] for r in a.execute('pragma table_info('+table+')')]
  if cols!=[r[1] for r in b.execute('pragma table_info('+table+')')]:raise ValueError('TABLE_SCHEMA_CHANGED:'+table)
  q='select * from '+table+' order by '+','.join('"'+col+'"' for col in cols)
  aa=a.execute(q).fetchall();bb=b.execute(q).fetchall()
  if aa!=bb:raise ValueError('NONPERSON_TABLE_CHANGED:'+table)
  checked[table]=len(aa)
 return dict(exact_preserved_tables=checked,person_fields_changed=person_diff(rows(a),rows(b)))

def baseline(path,year):
 pins=json.loads((ROOT/'historical_sources.json').read_text());pin=pins[str(year)]
 if hashlib.sha256(path.read_bytes()).hexdigest()!=pin['source_zip_sha256']:raise ValueError('BASELINE_ZIP_SHA_MISMATCH')
 with zipfile.ZipFile(path) as z:
  if z.testzip():raise ValueError('BASELINE_ZIP_CORRUPT')
  raw=z.read('MASTER.sqlite3');m=json.loads(z.read('manifest.json'));audit=json.loads(z.read('AUDIT.json'))
 if m.get('year')!=year or m.get('status')!='CERTIFIED' or audit.get('status')!='CERTIFIED':raise ValueError('BASELINE_NOT_CERTIFIED_OR_WRONG_YEAR')
 digest=hashlib.sha256(raw).hexdigest()
 if digest!=pin['master_sha256'] or digest!=m['master_sha256']:raise ValueError('BASELINE_MASTER_SHA_MISMATCH')
 return raw,m,audit

def main():
 p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--db',type=Path);p.add_argument('--output',type=Path,default=Path('delivery'));p.add_argument('--verify-source-only',action='store_true');a=p.parse_args()
 if not 2010<=a.year<=2025:raise ValueError('HISTORICAL_YEAR_ONLY')
 raw,m,original_audit=baseline(a.source,a.year)
 if a.verify_source_only:print('BASELINE_VERIFIED',a.year,m['master_sha256']);return
 if not a.db:raise ValueError('WORKING_DB_REQUIRED')
 a.output.mkdir(parents=True,exist_ok=True)
 person=json.loads((a.output/f'person_repair_audit_{a.year}.json').read_text())
 if person['year']!=a.year or person['errors'] or person['pending_races'] or person['person_fields']['status']!='PASS':raise ValueError('PERSON_REPAIR_NOT_COMPLETE')
 old=sqlite3.connect(':memory:');old.deserialize(raw)
 work=sqlite3.connect('file:'+str(a.db.resolve())+'?mode=ro',uri=True)
 try:
  for c in [old,work]:
   if c.execute('pragma integrity_check').fetchone()[0]!='ok' or c.execute('pragma foreign_key_check').fetchall():raise ValueError('INVALID_SQLITE')
  verification=compare(old,work)
 finally:old.close();work.close()
 verification.update(year=a.year,source_master_sha256=m['master_sha256'],source_zip_sha256=hashlib.sha256(a.source.read_bytes()).hexdigest(),original_stage_evidence_reused_only_with_exact_nonperson_preservation=True)
 (a.output/f'person_preservation_{a.year}.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2))
 # Preserve original independent stage evidence only after checking every relevant
 # non-person table above. export_master reruns all admission checks itself.
 from jra_master.unified_export import export_master
 audit=export_master(a.year,a.db,a.output,original_audit['stages'])
 if audit['status']!='CERTIFIED':raise ValueError('MASTER_NOT_CERTIFIED:'+','.join(audit['blockers']))
 dest=a.output/f'{a.year}_JRA_MASTER.zip'
 if not dest.is_file():raise ValueError('MASTER_ARCHIVE_MISSING')
 with zipfile.ZipFile(dest) as z:
  if z.testzip():raise ValueError('EXPORTED_ZIP_CORRUPT')
  manifest=json.loads(z.read('manifest.json'))
  if manifest['status']!='CERTIFIED' or hashlib.sha256(z.read('MASTER.sqlite3')).hexdigest()!=manifest['master_sha256']:raise ValueError('INVALID_EXPORTED_MASTER')
 print('HISTORICAL_REPAIRED_MASTER_VERIFIED',a.year,dest.stat().st_size,flush=True)

if __name__=='__main__':main()
