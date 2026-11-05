"""Recompute causal person aggregates for all feature rows and reference dates."""
import argparse,io,json,sys,tempfile,zipfile
from pathlib import Path
import numpy as np,pandas as pd

def main():
 p=argparse.ArgumentParser();p.add_argument('--common',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 z=zipfile.ZipFile(a.common)
 with tempfile.TemporaryDirectory() as tmp:
  rt=Path(tmp)
  for n in z.namelist():
   if n.startswith('TRACE_1_1_0/research_runtime/') and n.endswith('.py') and '/tests/' not in n:(rt/Path(n).name).write_bytes(z.read(n))
  sys.path.insert(0,str(rt))
  import person_features_bulk
  from person_features import compute
  h=pd.read_pickle(io.BytesIO(z.read('TRACE_1_1_0/data/repaired_flat_history.pkl.gz')),compression='gzip');out=[]
  cols=[role+'_'+stat for role in ['jockey','trainer'] for stat in ['starts','win_rate','top3_rate','performance']]
  for cond in ['weekly_lag_history','previous_day_history']:
   d=pd.read_pickle(io.BytesIO(z.read(f'TRACE_1_1_0/data/repaired_features_{cond}.pkl.gz')),compression='gzip')
   print('PERSON_RECOMPUTE',cond,len(d),flush=True);rebuilt,status=person_features_bulk.compute(h,d)
   item=dict(condition=cond,rows=len(d),all_row_mismatches={col:int((~np.isclose(d[col],rebuilt[col],rtol=0,atol=1e-10,equal_nan=True)).sum()) for col in cols},status_mismatches={role:int(d[role+'_key_status'].ne(rebuilt[role+'_key_status']).sum()) for role in ['jockey','trainer']},reference_dates=[])
   for year in [2011,2016,2020,2025]:
    candidates=d[d.year.eq(year)&d.grade.isin(['GⅠ','GⅡ','GⅢ'])].race_date.sort_values().unique();day=str(candidates[len(candidates)//2]);q=d[d.race_date.eq(day)];cut=q.history_cutoff.iloc[0]
    ref,_=compute(h,q,cut,day,day+'T09:00:00+09:00',day+'T10:00:00+09:00')
    item['reference_dates'].append(dict(date=day,cutoff=cut,rows=len(q),mismatches={col:int((~np.isclose(q[col],ref[col],rtol=0,atol=1e-10,equal_nan=True)).sum()) for col in cols}))
   out.append(item);(a.output/'TRACE_PERSON_REFERENCE_AUDIT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print('PERSON_RECOMPUTE_DONE',cond,item['all_row_mismatches'],flush=True)
if __name__=='__main__':main()
