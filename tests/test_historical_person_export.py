import unittest,sys,sqlite3,json,tempfile,zipfile,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from historical_person_export import person_diff,compare
class RepairAdmission(unittest.TestCase):
 def row(self,**kwargs):return {('R',1):('H',kwargs)}
 def test_name_recovery(self):self.assertEqual(person_diff(self.row(jockey_name=None),self.row(jockey_name='騎手A')),{'jockey_name':1})
 def test_id_recovery(self):self.assertEqual(person_diff(self.row(jockey_id=None),self.row(jockey_id='1111')),{'jockey_id':1})
 def test_missing_official_id_is_allowed_unchanged(self):self.assertEqual(person_diff(self.row(jockey_id=None),self.row(jockey_id=None)),{})
 def test_existing_id_cannot_change(self):
  with self.assertRaises(ValueError):person_diff(self.row(jockey_id='1111'),self.row(jockey_id='2222'))
 def test_performance_cannot_change(self):
  with self.assertRaises(ValueError):person_diff(self.row(body_weight_kg=450),self.row(body_weight_kg=460))
 def test_runner_cannot_disappear(self):
  with self.assertRaises(ValueError):person_diff(self.row(),{})
 def test_horse_cannot_change(self):
  with self.assertRaises(ValueError):person_diff(self.row(),{('R',1):('X',{})})
 def test_existing_name_cannot_be_replaced(self):
  with self.assertRaises(ValueError):person_diff(self.row(jockey_name='A'),self.row(jockey_name='B'))
 def db(self,result):
  c=sqlite3.connect(':memory:');c.execute('create table results (race_id text,horse_number int,payload_json text)');c.execute('insert into results values (?,?,?)',('R',1,json.dumps(result)));c.execute('create table runners (race_id text,horse_number int,horse_id text,payload_json text)');c.execute('insert into runners values (?,?,?,?)',('R',1,'H','{}'));return c
 def test_changed_result_table_blocks_export(self):
  a=self.db({'finish_position':1});b=self.db({'finish_position':2})
  try:
   with self.assertRaisesRegex(ValueError,'NONPERSON_TABLE_CHANGED'):compare(a,b)
  finally:a.close();b.close()
 def test_exact_core_is_retained(self):
  a=self.db({'finish_position':1});b=self.db({'finish_position':1})
  try:self.assertEqual(compare(a,b)['exact_preserved_tables'],{'results':1})
  finally:a.close();b.close()

class BaselineAdmission(unittest.TestCase):
 def test_wrong_zip_hash_cannot_be_adopted(self):
  import historical_person_export as m
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'source.zip';p.write_bytes(b'wrong-source')
   with self.assertRaisesRegex(ValueError,'BASELINE_ZIP_SHA_MISMATCH'):m.baseline(p,2025)
