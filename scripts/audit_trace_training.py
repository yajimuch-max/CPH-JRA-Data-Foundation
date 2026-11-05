"""Read-only reconciliation of TRACE v1.1.0 history/features against annual masters.
Run with --sources directory containing original ZIPs and the COMMON ZIP.
No network, pickle files must be trusted project artifacts. Reports limits explicitly.
"""
import argparse,hashlib,io,json,sqlite3,tempfile,zipfile,sys
from pathlib import Path
import numpy as np
import pandas as pd
INACTIVE=['取消','除外','SCRATCHED','EXCLUDED','CANCELLED']
KEY=['race_id','horse_number']
PERSON=['jockey_id','jockey_name','trainer_id','trainer_name']

def equal(a,b):
 return a.eq(b).fillna(False)|(a.isna()&b.isna())

def main():
 p=argparse.ArgumentParser();p.add_argument('--sources',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 common=zipfile.ZipFile(a.sources/'06-TRACE_RESEARCH_COMMON_v1.1.0.zip')
 history=pd.read_pickle(io.BytesIO(common.read('TRACE_1_1_0/data/repaired_flat_history.pkl.gz')),compression='gzip')
 report=dict(scope='Local originals versus repaired history and both feature tables; no claim of all official HTML fields or annual calendar completeness',years=[],history_rows=len(history),history_duplicates=int(history.duplicated(KEY).sum()))
 examples=[]
 with tempfile.TemporaryDirectory() as tmp:
  for year in range(2010,2026):
   path=next(a.sources.glob(f'*-{year}_JRA_MASTER.zip'));z=zipfile.ZipFile(path);raw=z.read('MASTER.sqlite3');db=Path(tmp)/'read.sqlite3';db.write_bytes(raw);c=sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)
   q="""select r.race_id,r.race_date,r.track,r.surface,r.distance_m,r.grade,r.going,r.weather,r.class_text,
   s.horse_number,s.horse_id,s.horse_name,s.frame_no,s.sex_age,s.assigned_weight_kg,s.body_weight_kg,s.body_weight_change_kg,s.blinker_worn_confirmed,
   json_extract(u.payload_json,'$.jockey_id') jockey_id,json_extract(u.payload_json,'$.trainer_id') trainer_id,
   json_extract(u.payload_json,'$.jockey_name') jockey_name,json_extract(u.payload_json,'$.trainer_name') trainer_name,
   s.finish_position,s.finish_status,s.runner_last_3f
   from race_summary r join runner_summary s using(race_id) join runners u on u.race_id=s.race_id and u.horse_number=s.horse_number
   where r.race_type='FLAT'"""
   old=pd.read_sql_query(q,c).set_index(KEY).sort_index();new=history[history.year.eq(year)].set_index(KEY).sort_index();same=old.index.equals(new.index)
   item=dict(year=year,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),sqlite_sha256=hashlib.sha256(raw).hexdigest(),integrity=c.execute('pragma integrity_check').fetchone()[0],foreign_key_violations=len(c.execute('pragma foreign_key_check').fetchall()),races=c.execute('select count(*) from races').fetchone()[0],runners=c.execute('select count(*) from runners').fetchone()[0],flat_rows=len(old),history_rows=len(new),identical_history_keys=same)
   item['missing_join_rows']={t:c.execute('select count(*) from runners u left join '+t+' t using(race_id,horse_number) where t.race_id is null').fetchone()[0] for t in ['results','win_odds']}
   item['missing_race_payouts']=c.execute('select count(*) from races r where not exists(select 1 from payouts p where p.race_id=r.race_id)').fetchone()[0]
   item['refund_races']=c.execute("select count(distinct race_id) from payouts where bet_type='REFUND'").fetchone()[0]
   item['inactive_rows_without_refund_record']=c.execute("select count(*) from results r where json_extract(r.payload_json,'$.finish_status') in ('取消','除外') and not exists(select 1 from payouts p where p.race_id=r.race_id and p.bet_type='REFUND')").fetchone()[0]
   item['missing_person_names_all_runners']={role:c.execute("select count(*) from runners where json_extract(payload_json,?) is null or trim(json_extract(payload_json,?))=''",('$.'+role+'_name','$.'+role+'_name')).fetchone()[0] for role in ['jockey','trainer']}
   item['missing_person_ids_all_runners']={role:c.execute("select count(*) from runners where json_extract(payload_json,?) is null or trim(json_extract(payload_json,?))=''",('$.'+role+'_id','$.'+role+'_id')).fetchone()[0] for role in ['jockey','trainer']}
   item['history_changed_columns']={};item['illegal_nonmissing_person_changes']={}
   if same:
    for col in old:
     eq=equal(old[col],new[col]);n=int((~eq).sum())
     if n:
      item['history_changed_columns'][col]=n
      if col in PERSON:
       before_present=old[col].notna()&old[col].astype(str).str.strip().ne('');item['illegal_nonmissing_person_changes'][col]=int((~eq&before_present).sum())
      if len(examples)<40:
       for ix in old.index[~eq][:2]:examples.append(dict(year=year,key=list(ix),column=col,before=str(old.at[ix,col]),after=str(new.at[ix,col])))
   c.close();report['years'].append(item);print('SOURCE_AUDIT',year,item['history_changed_columns'],flush=True)
 report['features']=[]
 for condition in ['weekly_lag_history','previous_day_history']:
  d=pd.read_pickle(io.BytesIO(common.read(f'TRACE_1_1_0/data/repaired_features_{condition}.pkl.gz')),compression='gzip')
  active=history[~history.finish_status.isin(INACTIVE)].set_index(KEY).sort_index();f=d.set_index(KEY).sort_index();same=f.index.equals(active.index)
  item=dict(condition=condition,rows=len(d),races=int(d.race_id.nunique()),duplicates=int(d.duplicated(KEY).sum()),identical_active_history_keys=same,cutoff_not_before_race=int((d.history_cutoff>=d.race_date).sum()),latest_history_after_cutoff=int((d.latest_history_used.notna()&(d.latest_history_used>d.history_cutoff)).sum()),infinite_numeric_cells=int(np.isinf(d.select_dtypes('number').to_numpy()).sum()),market_columns=[col for col in d if any(t in col.lower() for t in ['odds','popularity','payout'])])
  if same:
   shared=[col for col in active if col in f];item['source_value_mismatches']={col:int((~equal(active[col],f[col])).sum()) for col in shared}
   pos=pd.to_numeric(active.finish_position,errors='coerce');field=active.groupby(level='race_id').size().reindex(active.index.get_level_values('race_id')).to_numpy();item['field_size_mismatches']=int((f.field_size.to_numpy()!=field).sum())
   item['label_mismatches']={col:int((f[col].to_numpy()!=(pos<=k).astype(float).to_numpy()).sum()) for k,col in enumerate(['win','top2','top3'],1)}
   perf=(1-(pos.fillna(pd.Series(field+1,index=pos.index))-1)/field).clip(0,1);item['performance_mismatches']=int((~np.isclose(perf,f.performance,atol=1e-12)).sum())
  item['missing_cells']={col:int(n) for col,n in d.isna().sum().items() if n};item['person_key_status']={role:d[role+'_key_status'].value_counts(dropna=False).to_dict() for role in ['jockey','trainer']}
  item['measurement_missing_by_year']={int(year):{col:int(group[col].isna().sum()) for col in d if col.startswith('measurement_')} for year,group in d.groupby('year')}
  report['features'].append(item);print('FEATURE_AUDIT',condition,len(d),same,flush=True)
 report['change_examples']=examples
 report['limitations']=['Official HTML has not been fetched for every race; source completeness and truth are not proved by internal joins.','NULL IDs can be genuine unavailable official links; no fabricated IDs.','Missing history, unconfirmed blinkers and unpublished track measurements are reported, not blanket-imputed.','Person aggregate calculations, all other derived features and source calendar completeness need separate causal/reference verification.']
 dest=a.output/'TRACE_TRAINING_AUDIT.json';dest.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=lambda x:int(x)));print(dest)
if __name__=='__main__':main()
