#!/usr/bin/env python3
"""CodeX Library - localhost-only zero-dependency SQLite web application.
A web adaptation of https://github.com/kichiya999x/codex_library_system
"""
from __future__ import annotations
import argparse
import csv
from datetime import date, datetime, timedelta
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
DB_FILE = Path(os.getenv('CODEX_DB_PATH', str(ROOT / 'codex_library.sqlite3')))
LOCK = RLock()
DAYS = {'Book': 7, 'Journal': 3, 'Magazine': 1, 'Thesis Book': 2}

class AppError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code

@contextmanager
def connect():
    db = sqlite3.connect(str(DB_FILE), timeout=10, isolation_level=None, check_same_thread=False)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        yield db
    finally:
        db.close()

def init_db(reset=False):
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK, connect() as db:
        if reset:
            db.executescript('DROP TABLE IF EXISTS loans; DROP TABLE IF EXISTS materials; DROP TABLE IF EXISTS borrowers;')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS borrowers (
                id INTEGER PRIMARY KEY CHECK(id > 0), first_name TEXT NOT NULL,
                last_name TEXT NOT NULL, middle_name TEXT NOT NULL DEFAULT '',
                gender TEXT NOT NULL DEFAULT '', birthday TEXT NOT NULL DEFAULT '',
                contact TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '', violations INTEGER NOT NULL DEFAULT 0
                CHECK(violations BETWEEN 0 AND 3), active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS materials (
                id TEXT PRIMARY KEY, type TEXT NOT NULL CHECK(type IN ('Book','Journal','Magazine','Thesis Book')),
                title TEXT NOT NULL, author TEXT NOT NULL DEFAULT '',
                publisher TEXT NOT NULL DEFAULT '', year INTEGER NOT NULL,
                copies_total INTEGER NOT NULL CHECK(copies_total >= 0),
                copies_available INTEGER NOT NULL CHECK(copies_available >= 0),
                active INTEGER NOT NULL DEFAULT 1,
                CHECK(copies_available <= copies_total)
            );
            CREATE TABLE IF NOT EXISTS loans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                borrower_id INTEGER NOT NULL REFERENCES borrowers(id),
                material_id TEXT NOT NULL REFERENCES materials(id),
                borrowed_at TEXT NOT NULL, due_at TEXT NOT NULL,
                returned_at TEXT DEFAULT NULL, was_late INTEGER NOT NULL DEFAULT 0
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_loan_per_borrower
            ON loans(borrower_id) WHERE returned_at IS NULL;
            CREATE INDEX IF NOT EXISTS loans_material_id ON loans(material_id);
        ''')
        if db.execute('SELECT COUNT(*) FROM borrowers').fetchone()[0] == 0 and db.execute('SELECT COUNT(*) FROM materials').fetchone()[0] == 0:
            seed_db(db)

def seed_db(db):
    """Fictional demo records; intentionally not copied from GitHub borrowers.txt."""
    today = date.today()
    borrowers = [
        (1001,'Amelia','Reyes','', 'Female','2003-05-16','09170000001','amelia.reyes@example.com','Quezon City',0,1),
        (1002,'Noah','Santos','', 'Male','2002-11-08','09170000002','noah.santos@example.com','Manila',0,1),
        (1003,'Isabella','Cruz','', 'Female','2004-01-22','09170000003','isabella.cruz@example.com','Makati City',1,1),
        (1004,'Liam','Garcia','', 'Male','2001-08-10','09170000004','liam.garcia@example.com','Pasig City',0,1),
        (1005,'Sophia','Mendoza','', 'Female','2003-07-03','09170000005','sophia.mendoza@example.com','Mandaluyong',0,1),
        (1006,'Ethan','Torres','', 'Male','2002-04-18','09170000006','ethan.torres@example.com','Marikina City',2,1),
        (1007,'Olivia','Ramos','', 'Female','2004-09-12','09170000007','olivia.ramos@example.com','Taguig City',0,1),
        (1008,'Lucas','Flores','', 'Male','2003-12-02','09170000008','lucas.flores@example.com','San Juan City',0,1),
    ]
    db.executemany('INSERT INTO borrowers VALUES (?,?,?,?,?,?,?,?,?,?,?)', borrowers)
    materials = [
        ('BK-001','Book','Clean Code','Robert C. Martin','Prentice Hall',2008,5,4,1),
        ('BK-002','Book','The Pragmatic Programmer','Andrew Hunt & David Thomas','Addison-Wesley',2019,4,3,1),
        ('BK-003','Book','Introduction to Algorithms','Thomas H. Cormen et al.','MIT Press',2022,3,3,1),
        ('BK-004','Book','Design of Everyday Things','Don Norman','Basic Books',2013,4,4,1),
        ('BK-005','Book','Database System Concepts','Abraham Silberschatz et al.','McGraw-Hill',2019,2,2,1),
        ('JR-001','Journal','Journal of Information Systems','', 'Academic Press',2024,6,5,1),
        ('JR-002','Journal','Computing Research Review','', 'Springer',2025,4,4,1),
        ('MG-001','Magazine','Wired — Future of Technology','','Condé Nast',2025,8,8,1),
        ('MG-002','Magazine','National Geographic — Exploration','','National Geographic',2024,6,6,1),
        ('TH-001','Thesis Book','Digital Library Adoption in Universities','A. Dela Cruz','University Archive',2023,2,2,1),
        ('TH-002','Thesis Book','Cybersecurity Awareness Among Students','M. Castillo','University Archive',2024,2,1,1),
        ('BK-006','Book','Deep Work','Cal Newport','Grand Central',2016,3,3,1),
    ]
    db.executemany('INSERT INTO materials VALUES (?,?,?,?,?,?,?,?,?)', materials)
    # Reconcile inventory by seeding the four active loans recorded above.
    active = [
        (1001,'BK-001',-3,4),
        (1002,'BK-002',-2,5),
        (1003,'JR-001',-4,-1),
        (1005,'TH-002',-1,1),
    ]
    for bid,mid,borrow_offset,due_offset in active:
        db.execute('INSERT INTO loans (borrower_id, material_id, borrowed_at, due_at) VALUES(?,?,?,?)',
                   (bid,mid,(today+timedelta(days=borrow_offset)).isoformat(),(today+timedelta(days=due_offset)).isoformat()))
    historical = [
        (1004,'BK-003',-26,-19,-20,0),
        (1006,'MG-001',-18,-17,-15,1),
        (1007,'BK-004',-12,-5,-8,0),
        (1008,'JR-002',-10,-7,-7,0),
        (1003,'BK-006',-18,-11,-10,1),
    ]
    for bid,mid,borrow,due,returned,late in historical:
        db.execute('INSERT INTO loans (borrower_id,material_id,borrowed_at,due_at,returned_at,was_late) VALUES(?,?,?,?,?,?)',
                   (bid,mid,*[(today+timedelta(days=d)).isoformat() for d in (borrow,due,returned)],late))

def rdict(row):
    return dict(row) if row else None

def required(data, name, max_len=160):
    value = str(data.get(name, '')).strip()
    if not value:
        raise AppError(f'{name.replace("_"," ").capitalize()} is required.')
    if len(value) > max_len:
        raise AppError(f'{name.replace("_"," ").capitalize()} is too long.')
    return value

def optional(data,name,max_len=160):
    value = str(data.get(name,'') or '').strip()
    if len(value)>max_len: raise AppError(f'{name.replace("_"," ").capitalize()} is too long.')
    return value

def int_field(data,name,minimum=0,maximum=999999999):
    try: value=int(data.get(name, ''))
    except (ValueError,TypeError): raise AppError(f'{name.replace("_"," ").capitalize()} must be a whole number.')
    if value < minimum or value > maximum: raise AppError(f'{name.replace("_"," ").capitalize()} must be between {minimum} and {maximum}.')
    return value

def borrower_fields(data, editing=False):
    f = {key:required(data,key,100) for key in ('first_name','last_name')}
    f.update({key:optional(data,key,200) for key in ('middle_name','gender','birthday','contact','email','address')})
    if f['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',f['email']): raise AppError('Enter a valid email address.')
    if f['birthday']:
        try:
            if date.fromisoformat(f['birthday']) > date.today(): raise AppError('Birthday cannot be in the future.')
        except ValueError: raise AppError('Birthday must use YYYY-MM-DD.')
    if f['contact'] and not re.fullmatch(r'[0-9+ ()-]{7,24}',f['contact']): raise AppError('Enter a valid contact number.')
    return f

def material_fields(data):
    f={'type':required(data,'type'),'title':required(data,'title',220),
       'author':optional(data,'author',220),'publisher':optional(data,'publisher',160),
       'year':int_field(data,'year',1500,2100),'copies_total':int_field(data,'copies_total',0,100000)}
    if f['type'] not in DAYS: raise AppError('Unknown material type.')
    return f

def query(db, sql, args=()):
    return [dict(r) for r in db.execute(sql,args).fetchall()]

LOAN_SQL='''SELECT l.*, b.first_name || ' ' || b.last_name AS borrower_name,
 b.violations AS borrower_violations, m.title AS material_title, m.type AS material_type,
 CASE WHEN l.returned_at IS NOT NULL THEN 'Returned'
 WHEN l.due_at < date('now','localtime') THEN 'Overdue' ELSE 'Active' END AS status
 FROM loans l JOIN borrowers b ON b.id=l.borrower_id JOIN materials m ON m.id=l.material_id'''

def respond_api(method, route, payload, db):
    path = route.strip('/').split('/')
    if method=='GET' and route=='/api/overview':
        stats={
            'total_titles':db.execute('SELECT COUNT(*) FROM materials WHERE active=1').fetchone()[0],
            'total_copies':db.execute('SELECT COALESCE(SUM(copies_total),0) FROM materials WHERE active=1').fetchone()[0],
            'available_copies':db.execute('SELECT COALESCE(SUM(copies_available),0) FROM materials WHERE active=1').fetchone()[0],
            'active_borrowers':db.execute('SELECT COUNT(*) FROM borrowers WHERE active=1').fetchone()[0],
            'on_loan':db.execute('SELECT COUNT(*) FROM loans WHERE returned_at IS NULL').fetchone()[0],
            'overdue':db.execute("SELECT COUNT(*) FROM loans WHERE returned_at IS NULL AND due_at < date('now','localtime')").fetchone()[0],
            'returned':db.execute('SELECT COUNT(*) FROM loans WHERE returned_at IS NOT NULL').fetchone()[0]
        }
        return {'stats':stats, 'distribution':query(db,'SELECT type, COUNT(*) AS count FROM materials WHERE active=1 GROUP BY type ORDER BY count DESC'),
                'recent':query(db,LOAN_SQL+' ORDER BY COALESCE(l.returned_at,l.borrowed_at) DESC, l.id DESC LIMIT 6'),
                'due_soon':query(db,LOAN_SQL+" WHERE l.returned_at IS NULL ORDER BY l.due_at ASC LIMIT 5")}
    if method=='GET' and route=='/api/borrowers':
        return query(db,'''SELECT b.*, (SELECT COUNT(*) FROM loans l WHERE l.borrower_id=b.id AND l.returned_at IS NULL) AS active_loans,
             (SELECT COUNT(*) FROM loans l WHERE l.borrower_id=b.id) AS all_loans
             FROM borrowers b WHERE b.active=1 ORDER BY b.last_name,b.first_name''')
    if method=='POST' and route=='/api/borrowers':
        bid=int_field(payload,'id',1,999999999); f=borrower_fields(payload)
        try:
            db.execute('INSERT INTO borrowers (id, first_name,last_name,middle_name,gender,birthday,contact,email,address) VALUES (?,?,?,?,?,?,?,?,?)',
                (bid,*(f[k] for k in ('first_name','last_name','middle_name','gender','birthday','contact','email','address'))))
        except sqlite3.IntegrityError: raise AppError('That borrower ID already exists.',409)
        return {'ok':True,'id':bid}
    if len(path)==3 and path[:2]==['api','borrowers']:
        bid=int(path[2]) if path[2].isdigit() else -1
        b=rdict(db.execute('SELECT * FROM borrowers WHERE id=? AND active=1',(bid,)).fetchone())
        if not b: raise AppError('Borrower not found.',404)
        if method=='PUT':
            f=borrower_fields(payload)
            db.execute('UPDATE borrowers SET first_name=?, last_name=?, middle_name=?, gender=?,birthday=?, contact=?,email=?,address=? WHERE id=?',
                (*(f[k] for k in ('first_name','last_name','middle_name','gender','birthday','contact','email','address')),bid))
            return {'ok':True}
        if method=='DELETE':
            if db.execute('SELECT 1 FROM loans WHERE borrower_id=? AND returned_at IS NULL',(bid,)).fetchone():
                raise AppError('Return this borrower’s active material before archiving.',409)
            db.execute('UPDATE borrowers SET active=0 WHERE id=?',(bid,))
            return {'ok':True}
    if method=='GET' and len(path)==4 and path[:2]==['api','borrowers'] and path[3]=='history':
        return query(db,LOAN_SQL+' WHERE l.borrower_id=? ORDER BY l.id DESC',(path[2],))
    if method=='GET' and route=='/api/materials':
        return query(db,'''SELECT m.*, (SELECT COUNT(*) FROM loans l WHERE l.material_id=m.id AND l.returned_at IS NULL) AS checked_out
             FROM materials m WHERE m.active=1 ORDER BY m.title''')
    if method=='POST' and route=='/api/materials':
        mid=required(payload,'id',30).upper()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-_]{0,29}',mid):raise AppError('Material ID must contain letters, numbers, hyphens or underscores.')
        f=material_fields(payload)
        try:
            db.execute('INSERT INTO materials (id,type,title,author,publisher,year,copies_total,copies_available) VALUES (?,?,?,?,?,?,?,?)',
                  (mid,f['type'],f['title'],f['author'],f['publisher'],f['year'],f['copies_total'],f['copies_total']))
        except sqlite3.IntegrityError: raise AppError('That material ID already exists.',409)
        return {'ok':True,'id':mid}
    if len(path)==3 and path[:2]==['api','materials']:
        mid=path[2].upper()
        m=rdict(db.execute('SELECT * FROM materials WHERE id=? AND active=1',(mid,)).fetchone())
        if not m: raise AppError('Material not found.',404)
        if method=='PUT':
            f=material_fields(payload)
            checked_out=m['copies_total']-m['copies_available']
            if f['copies_total'] < checked_out: raise AppError(f'Total copies cannot be below {checked_out}; those copies are checked out.',409)
            db.execute('UPDATE materials SET type=?,title=?,author=?,publisher=?,year=?,copies_total=?,copies_available=? WHERE id=?',
                  (f['type'],f['title'],f['author'],f['publisher'],f['year'],f['copies_total'],f['copies_total']-checked_out,mid))
            return {'ok':True}
        if method=='DELETE':
            if db.execute('SELECT 1 FROM loans WHERE material_id=? AND returned_at IS NULL',(mid,)).fetchone():
                raise AppError('Return all checked-out copies before archiving this title.',409)
            db.execute('UPDATE materials SET active=0 WHERE id=?',(mid,))
            return {'ok':True}
    if method=='GET' and len(path)==4 and path[:2]==['api','materials'] and path[3]=='history':
        return query(db,LOAN_SQL+' WHERE l.material_id=? ORDER BY l.id DESC',(path[2],))
    if method=='GET' and route=='/api/loans':
        return query(db,LOAN_SQL+' WHERE l.returned_at IS NULL ORDER BY l.due_at ASC, l.id DESC')
    if method=='GET' and route=='/api/history':
        return query(db,LOAN_SQL+' ORDER BY l.id DESC')
    if method=='POST' and route=='/api/loans':
        bid=int_field(payload,'borrower_id',1,999999999)
        mid=required(payload,'material_id',30).upper()
        borrower=rdict(db.execute('SELECT * FROM borrowers WHERE id=? AND active=1',(bid,)).fetchone())
        material=rdict(db.execute('SELECT * FROM materials WHERE id=? AND active=1',(mid,)).fetchone())
        if not borrower:raise AppError('Select an active borrower.',404)
        if not material:raise AppError('Select an available material.',404)
        if borrower['violations']>=3: raise AppError('This borrower has reached the limit of 3 violations.',409)
        if db.execute('SELECT 1 FROM loans WHERE borrower_id=? AND returned_at IS NULL',(bid,)).fetchone():
            raise AppError('This borrower already has an active loan.',409)
        if material['copies_available']<=0: raise AppError('No copies available for this material.',409)
        borrowed=date.today()
        due=borrowed+timedelta(days=DAYS[material['type']])
        db.execute('INSERT INTO loans (borrower_id,material_id,borrowed_at,due_at) VALUES(?,?,?,?)',(bid,mid,borrowed.isoformat(),due.isoformat()))
        db.execute('UPDATE materials SET copies_available=copies_available-1 WHERE id=?',(mid,))
        return {'ok':True,'due_at':due.isoformat()}
    if method=='POST' and len(path)==4 and path[:2]==['api','loans'] and path[3]=='return':
        lid=int(path[2]) if path[2].isdigit() else -1
        loan=rdict(db.execute('SELECT * FROM loans WHERE id=? AND returned_at IS NULL',(lid,)).fetchone())
        if not loan: raise AppError('That active loan was not found.',404)
        today=date.today().isoformat(); late=int(today>loan['due_at'])
        db.execute('UPDATE loans SET returned_at=?,was_late=? WHERE id=?',(today,late,lid))
        db.execute('UPDATE materials SET copies_available=copies_available+1 WHERE id=?',(loan['material_id'],))
        if late:db.execute('UPDATE borrowers SET violations=MIN(3,violations+1) WHERE id=?',(loan['borrower_id'],))
        return {'ok':True,'late':bool(late)}
    if method=='POST' and route=='/api/demo/reset':
        if payload.get('confirmation')!='RESET DEMO':raise AppError('Type RESET DEMO to confirm.')
        db.execute('DELETE FROM loans')
        db.execute('DELETE FROM materials')
        db.execute('DELETE FROM borrowers')
        db.execute("DELETE FROM sqlite_sequence WHERE name='loans'")
        seed_db(db)
        return {'ok':True}
    if method=='GET' and route=='/api/export':
        return {'borrowers':query(db,'SELECT * FROM borrowers'),'materials':query(db,'SELECT * FROM materials'),
                'loans':query(db,'SELECT * FROM loans'),'exported_at':datetime.now().isoformat()}
    if method=='GET' and route=='/api/health':return {'ok':True,'name':'CodeX Library'}
    raise AppError('Endpoint not found.',404)

class Handler(BaseHTTPRequestHandler):
    server_version='CodeXLocal/1.0'
    def log_message(self, fmt, *args):
        if not self.path.startswith('/api/health'):
            super().log_message(fmt,*args)
    def response(self,status,data,content_type='application/json; charset=utf-8'):
        if isinstance(data,(dict,list)):
            body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        elif isinstance(data,str):body=data.encode('utf-8')
        else:body=data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)
    def handle_http(self,method):
        route=urlparse(self.path).path
        if route.startswith('/api/'):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size>1024*512:raise AppError('Request body is too large.',413)
                payload=json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(payload,dict):raise AppError('Expected a JSON object.')
                with LOCK, connect() as db:
                    if method!='GET':db.execute('BEGIN IMMEDIATE')
                    try:
                        result=respond_api(method,route,payload,db)
                        if method!='GET':db.execute('COMMIT')
                    except Exception:
                        if method!='GET' and db.in_transaction:db.execute('ROLLBACK')
                        raise
                self.response(200,result)
            except AppError as e:self.response(e.code,{'error':str(e)})
            except json.JSONDecodeError:self.response(400,{'error':'Invalid JSON data.'})
            except sqlite3.Error as e:
                print('Database error:',e);self.response(500,{'error':'Database operation failed.'})
            except Exception as e:
                print('Server error:',type(e).__name__,e);self.response(500,{'error':'Unexpected server error.'})
            return
        if method!='GET':return self.response(405,{'error':'Method not allowed.'})
        paths={'/':'index.html','/index.html':'index.html','/app.css':'app.css','/app.js':'app.js','/favicon.svg':'favicon.svg'}
        file=paths.get(route)
        if not file:return self.response(404,'Not found.','text/plain; charset=utf-8')
        mime={'html':'text/html; charset=utf-8','css':'text/css; charset=utf-8','js':'text/javascript; charset=utf-8','svg':'image/svg+xml'}[file.rsplit('.',1)[-1]]
        self.response(200,(STATIC/file).read_bytes(),mime)
    def do_GET(self):self.handle_http('GET')
    def do_POST(self):self.handle_http('POST')
    def do_PUT(self):self.handle_http('PUT')
    def do_DELETE(self):self.handle_http('DELETE')

def main():
    parser=argparse.ArgumentParser(description='CodeX Library (localhost only)')
    parser.add_argument('--port',type=int,default=8766, help='Preferred port (default: 8766, auto-fallback if unavailable)')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    init_db()
    # Keep other local projects (such as your portfolio on 8765) untouched.
    # If the preferred port is occupied, find the next available CodeX port.
    server=None
    chosen_port=None
    for candidate in range(args.port, min(args.port + 20, 65536)):
        try:
            server=ThreadingHTTPServer(('127.0.0.1',candidate),Handler)
            chosen_port=candidate
            break
        except OSError as error:
            if getattr(error, 'errno', None) not in (48, 98, 10048):
                raise
            print(f'Port {candidate} is occupied. Trying the next port...')
    if server is None:
        raise SystemExit('No available local port found. Close another CodeX instance or use --port to choose a port.')
    print(f'CodeX Library running at http://127.0.0.1:{chosen_port}')
    print(f'Database file: {DB_FILE}')
    print('Close this window / press Ctrl+C to stop.')
    if not args.no_browser:
        import webbrowser
        from threading import Timer
        Timer(0.6,lambda:webbrowser.open(f'http://127.0.0.1:{chosen_port}')).start()
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
