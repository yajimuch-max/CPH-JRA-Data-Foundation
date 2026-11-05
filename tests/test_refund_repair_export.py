import sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from refund_repair_export import preserve
class PreservationTests(unittest.TestCase):
 def setUp(self):
  self.a=sqlite3.connect(':memory:');self.a.executescript("create table runners(race_id,horse_number,horse_id,payload_json);insert into runners values('R',1,'H','{}');create table payouts(race_id,bet_type,line_number,payload_json);insert into payouts values('R','WIN',1,'{}');create table custom_learning_data(value);insert into custom_learning_data values(17);")
  self.b=sqlite3.connect(':memory:');self.a.backup(self.b)
 def tearDown(self):self.a.close();self.b.close()
 def test_refund_only_allowed(self):
  self.b.execute("insert into payouts values('R','REFUND',1,'{}')");preserve(self.a,self.b)
 def test_jockey_mutation_rejected(self):
  self.b.execute("update runners set payload_json='changed'")
  with self.assertRaises(ValueError):preserve(self.a,self.b)
 def test_normal_payout_change_rejected(self):
  self.b.execute("update payouts set payload_json='changed'")
  with self.assertRaises(ValueError):preserve(self.a,self.b)
 def test_unanticipated_learning_table_change_rejected(self):
  self.b.execute('update custom_learning_data set value=18')
  with self.assertRaises(ValueError):preserve(self.a,self.b)
 def test_new_unknown_table_allowed_but_existing_not_removed(self):
  self.b.execute('drop table custom_learning_data')
  with self.assertRaises(ValueError):preserve(self.a,self.b)
