"""Run: python -m unittest discover -s tests -v"""
from datetime import date, timedelta
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('codex_server',ROOT/'server.py')
s=importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)

class CodeXTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        s.DB_FILE=Path(self.temp.name)/'test.sqlite3'
        s.init_db()
    def tearDown(self):
        self.temp.cleanup()
    def call(self,method,path,data=None):
        with s.LOCK,s.connect() as db:
            if method!='GET':db.execute('BEGIN IMMEDIATE')
            try:
                result=s.respond_api(method,path,data or {},db)
                if method!='GET':db.execute('COMMIT')
                return result
            except:
                if method!='GET' and db.in_transaction:db.execute('ROLLBACK')
                raise
    def test_seed_and_dashboard(self):
        summary=self.call('GET','/api/overview')['stats']
        self.assertEqual((summary['total_titles'],summary['active_borrowers'],summary['on_loan']),(12,8,4))
        self.assertEqual(summary['total_copies']-summary['available_copies'],4)
    def test_borrower_create_update_archive(self):
        b={'id':9000,'first_name':'Demo','last_name':'Tester','email':'demo@example.com','contact':'09170000000'}
        self.call('POST','/api/borrowers',b)
        with self.assertRaises(s.AppError):self.call('POST','/api/borrowers',b)
        b.update(first_name='Updated')
        self.call('PUT','/api/borrowers/9000',b)
        self.assertTrue(any(x['first_name']=='Updated' for x in self.call('GET','/api/borrowers')))
        self.call('DELETE','/api/borrowers/9000')
        self.assertFalse(any(x['id']==9000 for x in self.call('GET','/api/borrowers')))
    def test_material_create_update_archive(self):
        m={'id':'TEST-99','type':'Book','title':'Portfolio Testing','author':'A. Example','year':2024,'copies_total':2}
        self.call('POST','/api/materials',m)
        self.assertEqual(next(x for x in self.call('GET','/api/materials') if x['id']=='TEST-99')['copies_available'],2)
        m['copies_total']=3; self.call('PUT','/api/materials/TEST-99',m)
        self.call('DELETE','/api/materials/TEST-99')
        self.assertFalse(any(x['id']=='TEST-99' for x in self.call('GET','/api/materials')))
    def test_checkout_and_return_restores_stock(self):
        before=next(m for m in self.call('GET','/api/materials') if m['id']=='BK-003')['copies_available']
        result=self.call('POST','/api/loans',{'borrower_id':1004,'material_id':'BK-003'})
        self.assertEqual(result['due_at'],(date.today()+timedelta(days=7)).isoformat())
        after=next(m for m in self.call('GET','/api/materials') if m['id']=='BK-003')['copies_available']
        self.assertEqual(after,before-1)
        with self.assertRaises(s.AppError):self.call('POST','/api/loans',{'borrower_id':1004,'material_id':'BK-003'})
        lid=next(l for l in self.call('GET','/api/loans') if l['borrower_id']==1004)['id']
        self.assertFalse(self.call('POST',f'/api/loans/{lid}/return')['late'])
        self.assertEqual(next(m for m in self.call('GET','/api/materials') if m['id']=='BK-003')['copies_available'],before)
        self.assertTrue(any(x['id']==lid and x['returned_at'] for x in self.call('GET','/api/history')))
    def test_return_overdue_adds_violation(self):
        lid=next(l for l in self.call('GET','/api/loans') if l['material_id']=='JR-001')['id']
        self.assertTrue(self.call('POST',f'/api/loans/{lid}/return')['late'])
        b=next(b for b in self.call('GET','/api/borrowers') if b['id']==1003)
        self.assertEqual(b['violations'],2)
    def test_archiving_active_loan_is_blocked(self):
        for meth,route in [('DELETE','/api/borrowers/1001'),('DELETE','/api/materials/BK-001')]:
            with self.assertRaises(s.AppError):self.call(meth,route)
    def test_low_inventory_and_violation_limit(self):
        with s.connect() as db:
            db.execute('UPDATE borrowers SET violations=3 WHERE id=1004')
        with self.assertRaises(s.AppError):self.call('POST','/api/loans',{'borrower_id':1004,'material_id':'BK-003'})
        m=next(m for m in self.call('GET','/api/materials') if m['id']=='BK-001')
        with self.assertRaises(s.AppError):self.call('PUT','/api/materials/BK-001',{**m,'copies_total':0})
    def test_history_preserved_when_archived(self):
        self.call('DELETE','/api/borrowers/1004')
        history=self.call('GET','/api/borrowers/1004/history')
        self.assertTrue(history)
        self.assertEqual(history[0]['borrower_name'],'Liam Garcia')
    def test_reset_records(self):
        self.call('POST','/api/borrowers',{'id':9000,'first_name':'A','last_name':'B'})
        self.call('POST','/api/demo/reset',{'confirmation':'RESET DEMO'})
        self.assertEqual(len(self.call('GET','/api/borrowers')),8)
    def test_export(self):
        data=self.call('GET','/api/export')
        self.assertEqual(len(data['materials']),12)
        self.assertIn('exported_at',data)

if __name__=='__main__':unittest.main()
