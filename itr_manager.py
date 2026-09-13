import os, sqlite3, re
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash

DB_PATH = os.environ.get('ITR_DB_PATH', os.path.join(os.path.dirname(__file__), 'itr.sqlite3'))
itr = Blueprint('itr', __name__, url_prefix='/itr')

FIELDS = [
    ('TRADING','Opening Stock'),('TRADING','Purchases'),('TRADING','Direct Expenses'),
    ('TRADING','Sales'),('TRADING','Commission / Discounts'),('TRADING','Closing Stock'),('TRADING','Gross Profit'),
    ('P&L','Salary'),('P&L','Rent'),('P&L','Electricity Charges'),('P&L','Telephone Expenses'),
    ('P&L','Repairs & Maintenance'),('P&L','Miscellaneous Expenses'),('P&L','Depreciation'),('P&L','Interest'),('P&L','Other Expenses'),('P&L','Net Profit'),
    ('BALANCE_SHEET','Capital Account'),('BALANCE_SHEET','Fixed Assets'),('BALANCE_SHEET','Depreciation'),('BALANCE_SHEET','Investments'),
    ('BALANCE_SHEET','Loan'),('BALANCE_SHEET','Advance / Deposits & Advances'),('BALANCE_SHEET','Closing Stock'),('BALANCE_SHEET','Debtors'),('BALANCE_SHEET','Creditors'),
    ('BALANCE_SHEET','Bank'),('BALANCE_SHEET','Cash'),('BALANCE_SHEET','Other Assets'),('BALANCE_SHEET','Other Liabilities')
]

VARIANTS = {
    'sales': 'Sales', 'by sales': 'Sales', 'sales a/c': 'Sales',
    'purchases': 'Purchases', 'to purchases': 'Purchases', 'purchases a/c': 'Purchases',
    'opening stock': 'Opening Stock', 'to opening stock': 'Opening Stock',
    'closing stock': 'Closing Stock', 'by closing stock': 'Closing Stock',
    'gross profit': 'Gross Profit', 'gross prafit': 'Gross Profit', 'gross prafit c/d': 'Gross Profit',
    'salaries': 'Salary', 'salary': 'Salary', 'salaries & wages': 'Salary',
    'shop rent': 'Rent', 'rent': 'Rent',
    'electricity charges': 'Electricity Charges', 'electicity & fual charges': 'Electricity Charges',
    'telephone expenses': 'Telephone Expenses', 'telrphone&net charges': 'Telephone Expenses',
    'repairs & maintenance': 'Repairs & Maintenance', 'shop maintenance': 'Repairs & Maintenance',
    'depreciation': 'Depreciation', 'interest to bank': 'Interest', 'interest': 'Interest',
    'net profit': 'Net Profit', 'capital account': 'Capital Account', 'capital account of': 'Capital Account',
    'funiture': 'Fixed Assets', 'furniture': 'Fixed Assets', 'loan': 'Loan',
    'advance': 'Advance / Deposits & Advances', 'deposits & advances': 'Advance / Deposits & Advances',
    'bank balance': 'Bank', 'cash in hand': 'Cash', 'cash in bank & hand': 'Cash',
    'debtors': 'Debtors', 'creditors': 'Creditors', 'investments': 'Investments'
}

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def init_db():
    con = db()
    con.executescript('''
    CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT, client_name TEXT NOT NULL, proprietor_name TEXT, address TEXT, pan TEXT, contact TEXT, business_type TEXT, notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS financial_years(id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER NOT NULL, financial_year TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', source_pdf_name TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(client_id,financial_year), FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS account_values(id INTEGER PRIMARY KEY AUTOINCREMENT, financial_year_id INTEGER NOT NULL, statement_type TEXT NOT NULL, field_key TEXT NOT NULL, field_label TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0, source_type TEXT NOT NULL DEFAULT 'MANUAL', growth_method TEXT NOT NULL DEFAULT 'AUTO_GROWTH', growth_percent REAL NOT NULL DEFAULT 10, UNIQUE(financial_year_id,statement_type,field_key), FOREIGN KEY(financial_year_id) REFERENCES financial_years(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS projection_settings(id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, field_key TEXT NOT NULL, growth_percent REAL NOT NULL DEFAULT 10, growth_method TEXT NOT NULL DEFAULT 'AUTO_GROWTH', UNIQUE(client_id,field_key), FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS field_mappings(id INTEGER PRIMARY KEY AUTOINCREMENT, variant_text TEXT NOT NULL, standard_field TEXT NOT NULL, statement_type TEXT NOT NULL, UNIQUE(variant_text,standard_field,statement_type));
    ''')
    con.commit(); con.close()

def ensure_defaults(con, client_id):
    for _, field in FIELDS:
        con.execute('INSERT OR IGNORE INTO projection_settings(client_id,field_key,growth_percent,growth_method) VALUES(?,?,10,"AUTO_GROWTH")',(client_id,field))

def year_rows(con, client_id):
    return con.execute('SELECT * FROM financial_years WHERE client_id=? ORDER BY financial_year DESC',(client_id,)).fetchall()

def get_values(con, fyid):
    return con.execute('SELECT * FROM account_values WHERE financial_year_id=? ORDER BY statement_type,id',(fyid,)).fetchall()

def create_values_from_previous(con, fyid, previous_id, client_id):
    prev = {r['field_key']: r for r in get_values(con, previous_id)} if previous_id else {}
    settings = {r['field_key']: r for r in con.execute('SELECT * FROM projection_settings WHERE client_id=?',(client_id,)).fetchall()}
    for statement, field in FIELDS:
        p = prev.get(field); s = settings.get(field)
        base = float(p['amount']) if p else 0
        pct = float(s['growth_percent']) if s else 10
        method = s['growth_method'] if s else 'AUTO_GROWTH'
        amount = base * (1+pct/100) if method == 'AUTO_GROWTH' else base
        con.execute('INSERT OR REPLACE INTO account_values(financial_year_id,statement_type,field_key,field_label,amount,source_type,growth_method,growth_percent) VALUES(?,?,?,?,?,?,?,?)',(fyid,statement,field,field,amount,'CARRY_FORWARD',method,pct))

def parse_year(s):
    m = re.search(r'(20\d{2})\D*(20\d{2})', s or '')
    return f'{m.group(1)}-{m.group(2)[-2:]}' if m else None

@itr.before_app_request
def _init():
    init_db()

@itr.route('/')
def clients():
    con=db(); rows=con.execute('SELECT c.*, (SELECT MAX(financial_year) FROM financial_years f WHERE f.client_id=c.id) latest_fy FROM clients c ORDER BY c.client_name').fetchall(); con.close()
    return render_template('itr_clients.html', clients=rows)

@itr.route('/client/new', methods=['GET','POST'])
def new_client():
    if request.method=='POST':
        now=datetime.utcnow().isoformat(); con=db()
        cur=con.execute('INSERT INTO clients(client_name,proprietor_name,address,pan,contact,business_type,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',tuple(request.form.get(k,'').strip() for k in ['client_name','proprietor_name','address','pan','contact','business_type','notes'])+(now,now))
        ensure_defaults(con,cur.lastrowid); con.commit(); con.close(); return redirect(url_for('itr.client',client_id=cur.lastrowid))
    return render_template('itr_client_form.html')

@itr.route('/client/<int:client_id>')
def client(client_id):
    con=db(); c=con.execute('SELECT * FROM clients WHERE id=?',(client_id,)).fetchone(); years=year_rows(con,client_id); con.close()
    if not c: return 'Client not found',404
    return render_template('itr_client.html',client=c,years=years)

@itr.route('/client/<int:client_id>/year/new', methods=['POST'])
def new_year(client_id):
    fy=request.form.get('financial_year','').strip(); previous=request.form.get('previous_year_id')
    if not fy: flash('Financial year is required.'); return redirect(url_for('itr.client',client_id=client_id))
    con=db(); now=datetime.utcnow().isoformat()
    try:
        cur=con.execute('INSERT INTO financial_years(client_id,financial_year,status,created_at,updated_at) VALUES(?,?,"projected",?,?)',(client_id,fy,now,now)); fyid=cur.lastrowid
        ensure_defaults(con,client_id)
        prev_id=int(previous) if previous else None
        create_values_from_previous(con,fyid,prev_id,client_id)
        con.commit()
    except sqlite3.IntegrityError:
        con.rollback(); flash('That financial year already exists.')
    con.close(); return redirect(url_for('itr.year',fyid=fyid if 'fyid' in locals() else 0))

@itr.route('/year/<int:fyid>', methods=['GET','POST'])
def year(fyid):
    con=db(); fy=con.execute('SELECT f.*,c.client_name FROM financial_years f JOIN clients c ON c.id=f.client_id WHERE f.id=?',(fyid,)).fetchone()
    if not fy: con.close(); return 'Financial year not found',404
    if request.method=='POST':
        for k,v in request.form.items():
            if not k.startswith('amt_'): continue
            try: amount=float(v.replace(',',''))
            except: continue
            field=k[4:]; con.execute('UPDATE account_values SET amount=?,source_type="MANUAL" WHERE financial_year_id=? AND field_key=?',(amount,fyid,field))
        con.execute('UPDATE financial_years SET status="actual",updated_at=? WHERE id=?',(datetime.utcnow().isoformat(),fyid)); con.commit()
    vals=get_values(con,fyid); groups={}
    for r in vals: groups.setdefault(r['statement_type'],[]).append(r)
    con.close(); return render_template('itr_year.html',fy=fy,groups=groups)

@itr.route('/year/<int:fyid>/next', methods=['POST'])
def next_year(fyid):
    con=db(); old=con.execute('SELECT * FROM financial_years WHERE id=?',(fyid,)).fetchone()
    if not old: con.close(); return 'Year not found',404
    y=int(old['financial_year'][:4])+1; fy=f'{y}-{str(y+1)[-2:]}'; now=datetime.utcnow().isoformat()
    try:
        cur=con.execute('INSERT INTO financial_years(client_id,financial_year,status,created_at,updated_at) VALUES(?,?,"projected",?,?)',(old['client_id'],fy,now,now)); new_id=cur.lastrowid
        create_values_from_previous(con,new_id,fyid,old['client_id']); con.commit()
    except sqlite3.IntegrityError:
        new_id=con.execute('SELECT id FROM financial_years WHERE client_id=? AND financial_year=?',(old['client_id'],fy)).fetchone()['id']
    con.close(); return redirect(url_for('itr.year',fyid=new_id))
