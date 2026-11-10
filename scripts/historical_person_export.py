"""Verify a person-only repair against a pinned original, then audit/export it."""
import argparse,hashlib,json,sqlite3,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from repair_integrity import compare_person_repair as compare, person_diff

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

