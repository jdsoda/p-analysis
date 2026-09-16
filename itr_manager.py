import os, sqlite3, re
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
import pdfplumber
DB_PATH=os.environ.get('ITR_DB_PATH',os.path.join(os.path.dirname(__file__),'itr.sqlite3')); UPLOAD_DIR=os.environ.get('ITR_UPLOAD_DIR',os.path.join(os.path.dirname(__file__),'itr_uploads')); os.makedirs(UPLOAD_DIR,exist_ok=True); itr=Blueprint('itr',__name__,url_prefix='/itr')
FIELDS=[('TRADING','Opening Stock'),('TRADING','Purchases'),('TRADING','Direct Expenses'),('TRADING','Sales'),('TRADING','Commission / Discounts'),('TRADING','Closing Stock'),('TRADING','Gross Profit'),('P&L','Salary'),('P&L','Rent'),('P&L','Electricity Charges'),('P&L','Telephone Expenses'),('P&L','Repairs & Maintenance'),('P&L','Miscellaneous Expenses'),('P&L','Depreciation'),('P&L','Interest'),('P&L','Other Expenses'),('P&L','Net Profit'),('BALANCE_SHEET','Capital Account'),('BALANCE_SHEET','Fixed Assets'),('BALANCE_SHEET','Depreciation'),('BALANCE_SHEET','Investments'),('BALANCE_SHEET','Loan'),('BALANCE_SHEET','Advance / Deposits & Advances'),('BALANCE_SHEET','Closing Stock'),('BALANCE_SHEET','Debtors'),('BALANCE_SHEET','Creditors'),('BALANCE_SHEET','Bank'),('BALANCE_SHEET','Cash'),('BALANCE_SHEET','Other Assets'),('BALANCE_SHEET','Other Liabilities')]
VARIANTS={'sales':'Sales','by sales':'Sales','sales a/c':'Sales','purchases':'Purchases','to purchases':'Purchases','purchases a/c':'Purchases','opening stock':'Opening Stock','to opening stock':'Opening Stock','closing stock':'Closing Stock','by closing stock':'Closing Stock','gross profit':'Gross Profit','gross prafit':'Gross Profit','gross prafit c/d':'Gross Profit','salaries':'Salary','salary':'Salary','salaries & wages':'Salary','shop rent':'Rent','rent':'Rent','electricity charges':'Electricity Charges','electicity & fual charges':'Electricity Charges','telephone expenses':'Telephone Expenses','telrphone&net charges':'Telephone Expenses','repairs & maintenance':'Repairs & Maintenance','shop maintenance':'Repairs & Maintenance','depreciation':'Depreciation','interest to bank':'Interest','interest':'Interest','net profit':'Net Profit','capital account':'Capital Account','capital account of':'Capital Account','funiture':'Fixed Assets','furniture':'Fixed Assets','loan':'Loan','advance':'Advance / Deposits & Advances','deposits & advances':'Advance / Deposits & Advances','bank balance':'Bank','cash in hand':'Cash','cash in bank & hand':'Cash','debtors':'Debtors','creditors':'Creditors','investments':'Investments'}
BANK_CATEGORIES=[('UNCLASSIFIED','Review'),('MILK_SALES','Milk Sales'),('MILK_PURCHASES','Milk Purchases'),('BUSINESS_EXPENSE','Business Expense'),('LOAN_OR_TRANSFER','Loan / Own Transfer'),('PERSONAL_OR_OTHER','Personal / Other')]
def db():
 con=sqlite3.connect(DB_PATH); con.row_factory=sqlite3.Row; con.execute('PRAGMA foreign_keys=ON'); return con
def init_db():
 con=db(); con.executescript('''CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT,client_name TEXT NOT NULL,proprietor_name TEXT,address TEXT,pan TEXT,contact TEXT,business_type TEXT,notes TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS financial_years(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER NOT NULL,financial_year TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',source_pdf_name TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(client_id,financial_year),FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);CREATE TABLE IF NOT EXISTS account_values(id INTEGER PRIMARY KEY AUTOINCREMENT,financial_year_id INTEGER NOT NULL,statement_type TEXT NOT NULL,field_key TEXT NOT NULL,field_label TEXT NOT NULL,amount REAL NOT NULL DEFAULT 0,source_type TEXT NOT NULL DEFAULT 'MANUAL',growth_method TEXT NOT NULL DEFAULT 'AUTO_GROWTH',growth_percent REAL NOT NULL DEFAULT 10,UNIQUE(financial_year_id,statement_type,field_key),FOREIGN KEY(financial_year_id) REFERENCES financial_years(id) ON DELETE CASCADE);CREATE TABLE IF NOT EXISTS projection_settings(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER,field_key TEXT NOT NULL,growth_percent REAL NOT NULL DEFAULT 10,growth_method TEXT NOT NULL DEFAULT 'AUTO_GROWTH',UNIQUE(client_id,field_key),FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE);CREATE TABLE IF NOT EXISTS field_mappings(id INTEGER PRIMARY KEY AUTOINCREMENT,variant_text TEXT NOT NULL,standard_field TEXT NOT NULL,statement_type TEXT NOT NULL,UNIQUE(variant_text,standard_field,statement_type));CREATE TABLE IF NOT EXISTS bank_transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,financial_year_id INTEGER NOT NULL,txn_date TEXT,narration TEXT,debit REAL NOT NULL DEFAULT 0,credit REAL NOT NULL DEFAULT 0,balance REAL,channel TEXT,suggested_category TEXT NOT NULL DEFAULT 'UNCLASSIFIED',confidence REAL NOT NULL DEFAULT 0,final_category TEXT NOT NULL DEFAULT 'UNCLASSIFIED',notes TEXT,source_file TEXT,created_at TEXT NOT NULL,UNIQUE(financial_year_id,txn_date,narration,debit,credit,balance),FOREIGN KEY(financial_year_id) REFERENCES financial_years(id) ON DELETE CASCADE);''')
 for col,definition in [('bank_receipts_mode','TEXT NOT NULL DEFAULT "REVIEW"'),('bank_import_file','TEXT')]:
  try: con.execute(f'ALTER TABLE financial_years ADD COLUMN {col} {definition}')
  except sqlite3.OperationalError: pass
 con.commit(); con.close()
def ensure_defaults(con,client_id):
 for _,field in FIELDS: con.execute('INSERT OR IGNORE INTO projection_settings(client_id,field_key,growth_percent,growth_method) VALUES(?,?,10,"AUTO_GROWTH")',(client_id,field))
def year_rows(con,client_id): return con.execute('SELECT * FROM financial_years WHERE client_id=? ORDER BY financial_year DESC',(client_id,)).fetchall()
def get_values(con,fyid): return con.execute('SELECT * FROM account_values WHERE financial_year_id=? ORDER BY statement_type,id',(fyid,)).fetchall()
def create_values_from_previous(con,fyid,previous_id,client_id):
 prev={r['field_key']:r for r in get_values(con,previous_id)} if previous_id else {}; settings={r['field_key']:r for r in con.execute('SELECT * FROM projection_settings WHERE client_id=?',(client_id,)).fetchall()}
 for statement,field in FIELDS:
  p=prev.get(field); s=settings.get(field); base=float(p['amount']) if p else 0; pct=float(s['growth_percent']) if s else 10; method=s['growth_method'] if s else 'AUTO_GROWTH'; amount=base*(1+pct/100) if method=='AUTO_GROWTH' else base; con.execute('INSERT OR REPLACE INTO account_values(financial_year_id,statement_type,field_key,field_label,amount,source_type,growth_method,growth_percent) VALUES(?,?,?,?,?,?,?,?)',(fyid,statement,field,field,amount,'CARRY_FORWARD',method,pct))
def parse_year(s):
 m=re.search(r'(20\d{2})\D*(20\d{2})',s or ''); return f'{m.group(1)}-{m.group(2)[-2:]}' if m else None
def clean_amount(value):
 if value is None:return None
 s=str(value).replace(',','').replace('₹','').replace('Rs.','').replace('Rs','').strip(); s=re.sub(r'[^0-9.()\-]','',s)
 if not s:return None
 neg=s.startswith('(') and s.endswith(')'); s=s.strip('()')
 try:
  n=float(s); return -n if neg else n
 except ValueError:return None
def normalize_date(value):
 if not value:return None
 s=str(value).strip().lstrip("'").replace('.', '/').replace('-', '/')
 for fmt in ('%d/%b/%Y','%d/%b/%y','%d/%m/%Y','%d/%m/%y'):
  try:return datetime.strptime(s,fmt).strftime('%Y-%m-%d')
  except ValueError:continue
 return s
def fy_range(fy_text):
 m=re.search(r'(20\d{2})\s*[-/]\s*(\d{2,4})',fy_text or '')
 if not m:return None,None
 start=int(m.group(1)); end=int(m.group(2)); end=2000+end if end<100 else end
 return date(start,4,1),date(end,3,31)
def classify_bank_row(narration,debit,credit,cash_deposits_as_sales=False):
 n=(narration or '').lower()
 if cash_deposits_as_sales and credit>0 and any(x in n for x in ('cash deposit','cash dep','by cash','csh/casa_cr','casa_cr')):return 'MILK_SALES',0.98
 if credit>0 and any(x in n for x in ('milk','hatsun customer','customer receipt','upi/cr')):return 'MILK_SALES',0.72
 if debit>0 and any(x in n for x in ('hatsun','hapmilk','milk supplier','milk purchase')):return 'MILK_PURCHASES',0.96
 if any(x in n for x in ('loan','neft self','own transfer','transfer to self','capital')):return 'LOAN_OR_TRANSFER',0.90
 if debit>0 and any(x in n for x in ('electric','power','rent','salary','telephone','maintenance','repair')):return 'BUSINESS_EXPENSE',0.82
 if credit>0:return 'UNCLASSIFIED',0.25
 if debit>0:return 'PERSONAL_OR_OTHER',0.20
 return 'UNCLASSIFIED',0.0
def infer_channel(narration):
 n=(narration or '').lower()
 if 'upi' in n:return 'UPI'
 if 'neft' in n:return 'NEFT'
 if 'imps' in n:return 'IMPS'
 if 'rtgs' in n:return 'RTGS'
 if 'cash' in n:return 'CASH'
 if 'cheque' in n or 'chq' in n:return 'CHEQUE'
 return 'OTHER'
def parse_bank_pdf(path,cash_deposits_as_sales=False):
 rows=[]
 with pdfplumber.open(path) as pdf:
  for page in pdf.pages:
   for table in (page.extract_tables() or []):
    for raw in table:
     cells=[str(x).strip() if x is not None else '' for x in raw]
     if not any(cells):continue
     joined=' '.join(cells).lower()
     if 'date' in joined and ('debit' in joined or 'credit' in joined):continue
     di=next((i for i,c in enumerate(cells) if re.search(r'\b\d{1,2}[/-](?:[A-Za-z]{3}|\d{1,2})[/-](?:20)?\d{2}\b',c)),None)
     if di is None:continue
     if len(cells)>=7 and di==1 and clean_amount(cells[4]) is not None and clean_amount(cells[5]) is not None and clean_amount(cells[6]) is not None:
      txn_date=normalize_date(cells[1]); narration=cells[2]; debit=clean_amount(cells[4]) or 0; credit=clean_amount(cells[5]) or 0; balance=clean_amount(cells[6])
     else:continue
     if len(narration)<2 or any(x in narration.lower() for x in ('opening balance','closing balance','statement of account')):continue
     cat,confidence=classify_bank_row(narration,debit,credit,cash_deposits_as_sales); rows.append({'txn_date':txn_date,'narration':narration,'debit':round(abs(debit),2),'credit':round(abs(credit),2),'balance':balance,'channel':infer_channel(narration),'suggested_category':cat,'confidence':confidence})
 unique={(r['txn_date'],r['narration'],r['debit'],r['credit'],r['balance']):r for r in rows}; return list(unique.values())
@itr.before_app_request
def _init():init_db()
@itr.route('/')
def clients():
 con=db(); rows=con.execute('SELECT c.*,(SELECT MAX(financial_year) FROM financial_years f WHERE f.client_id=c.id) latest_fy FROM clients c ORDER BY c.client_name').fetchall(); con.close(); return render_template('itr_clients.html',clients=rows)
@itr.route('/client/new',methods=['GET','POST'])
def new_client():
 if request.method=='POST':
  now=datetime.utcnow().isoformat(); con=db(); cur=con.execute('INSERT INTO clients(client_name,proprietor_name,address,pan,contact,business_type,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',tuple(request.form.get(k,'').strip() for k in ['client_name','proprietor_name','address','pan','contact','business_type','notes'])+(now,now)); ensure_defaults(con,cur.lastrowid); con.commit(); con.close(); return redirect(url_for('itr.client',client_id=cur.lastrowid))
 return render_template('itr_client_form.html')
@itr.route('/client/<int:client_id>')
def client(client_id):
 con=db(); c=con.execute('SELECT * FROM clients WHERE id=?',(client_id,)).fetchone(); years=year_rows(con,client_id); con.close(); return render_template('itr_client.html',client=c,years=years) if c else ('Client not found',404)
@itr.route('/client/<int:client_id>/year/new',methods=['POST'])
def new_year(client_id):
 fy=request.form.get('financial_year','').strip(); previous=request.form.get('previous_year_id')
 if not fy:flash('Financial year is required.'); return redirect(url_for('itr.client',client_id=client_id))
 con=db(); now=datetime.utcnow().isoformat()
 try:
  cur=con.execute('INSERT INTO financial_years(client_id,financial_year,status,created_at,updated_at) VALUES(?,?,"projected",?,?)',(client_id,fy,now,now)); fyid=cur.lastrowid; ensure_defaults(con,client_id); create_values_from_previous(con,fyid,int(previous) if previous else None,client_id); con.commit()
 except sqlite3.IntegrityError:con.rollback(); flash('That financial year already exists.')
 con.close(); return redirect(url_for('itr.year',fyid=fyid if 'fyid' in locals() else 0))
@itr.route('/year/<int:fyid>',methods=['GET','POST'])
def year(fyid):
 con=db(); fy=con.execute('SELECT f.*,c.client_name FROM financial_years f JOIN clients c ON c.id=f.client_id WHERE f.id=?',(fyid,)).fetchone()
 if not fy:con.close(); return 'Financial year not found',404
 if request.method=='POST':
  for k,v in request.form.items():
   if not k.startswith('amt_'):continue
   try:amount=float(v.replace(',',''))
   except:continue
   con.execute('UPDATE account_values SET amount=?,source_type="MANUAL" WHERE financial_year_id=? AND field_key=?',(amount,fyid,k[4:]))
  con.execute('UPDATE financial_years SET status="actual",updated_at=? WHERE id=?',(datetime.utcnow().isoformat(),fyid)); con.commit()
 vals=get_values(con,fyid); groups={}
 for r in vals:groups.setdefault(r['statement_type'],[]).append(r)
 con.close(); return render_template('itr_year.html',fy=fy,groups=groups)
@itr.route('/year/<int:fyid>/bank-import',methods=['GET','POST'])
def bank_import(fyid):
 con=db(); fy=con.execute('SELECT f.*,c.client_name FROM financial_years f JOIN clients c ON c.id=f.client_id WHERE f.id=?',(fyid,)).fetchone()
 if not fy:con.close(); return 'Financial year not found',404
 if request.method=='POST':
  file=request.files.get('bank_pdf'); cash_mode=request.form.get('cash_deposits_as_sales')=='1'
  if not file or not file.filename.lower().endswith('.pdf'):flash('Please select a bank statement PDF.'); con.close(); return redirect(url_for('itr.bank_import',fyid=fyid))
  safe=secure_filename(file.filename); path=os.path.join(UPLOAD_DIR,f'{fyid}_{safe}'); file.save(path)
  try:
   rows=parse_bank_pdf(path,cash_mode); start,end=fy_range(fy['financial_year'])
   if start and end:
    rows=[r for r in rows if r['txn_date'] and start<=datetime.strptime(r['txn_date'],'%Y-%m-%d').date()<=end]
   now=datetime.utcnow().isoformat()
   for r in rows:con.execute('INSERT OR IGNORE INTO bank_transactions(financial_year_id,txn_date,narration,debit,credit,balance,channel,suggested_category,confidence,final_category,source_file,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(fyid,r['txn_date'],r['narration'],r['debit'],r['credit'],r['balance'],r['channel'],r['suggested_category'],r['confidence'],r['suggested_category'],safe,now))
   con.execute('UPDATE financial_years SET bank_receipts_mode=?,bank_import_file=?,updated_at=? WHERE id=?',('CASH_AS_SALES' if cash_mode else 'REVIEW',safe,now,fyid)); con.commit(); flash(f'Imported {len(rows)} transactions for {fy["financial_year"]}. Please review classification before posting.')
  except Exception as exc:con.rollback(); flash(f'Bank PDF could not be parsed: {exc}')
 txns=con.execute('SELECT * FROM bank_transactions WHERE financial_year_id=? ORDER BY txn_date,id',(fyid,)).fetchall(); totals=con.execute("SELECT COALESCE(SUM(credit),0) credits,COALESCE(SUM(debit),0) debits,COALESCE(SUM(CASE WHEN final_category='MILK_SALES' THEN credit ELSE 0 END),0) milk_sales,COALESCE(SUM(CASE WHEN final_category='MILK_PURCHASES' THEN debit ELSE 0 END),0) milk_purchases FROM bank_transactions WHERE financial_year_id=?",(fyid,)).fetchone(); con.close(); return render_template('itr_bank_import.html',fy=fy,txns=txns,totals=totals,categories=BANK_CATEGORIES)
@itr.route('/year/<int:fyid>/bank-import/save',methods=['POST'])
def save_bank_categories(fyid):
 con=db(); fy=con.execute('SELECT * FROM financial_years WHERE id=?',(fyid,)).fetchone()
 if not fy:con.close(); return 'Financial year not found',404
 allowed={x[0] for x in BANK_CATEGORIES}
 for key,value in request.form.items():
  if key.startswith('cat_'):
   try:tid=int(key[4:])
   except ValueError:continue
   if value in allowed:con.execute('UPDATE bank_transactions SET final_category=? WHERE id=? AND financial_year_id=?',(value,tid,fyid))
 con.commit(); con.close(); flash('Bank classifications saved. Nothing is posted to P&L until you apply totals.'); return redirect(url_for('itr.bank_import',fyid=fyid))
@itr.route('/year/<int:fyid>/bank-import/apply',methods=['POST'])
def apply_bank_totals(fyid):
 con=db(); fy=con.execute('SELECT * FROM financial_years WHERE id=?',(fyid,)).fetchone()
 if not fy:con.close(); return 'Financial year not found',404
 sales=con.execute("SELECT COALESCE(SUM(credit),0) FROM bank_transactions WHERE financial_year_id=? AND final_category='MILK_SALES'",(fyid,)).fetchone()[0]; purchases=con.execute("SELECT COALESCE(SUM(debit),0) FROM bank_transactions WHERE financial_year_id=? AND final_category='MILK_PURCHASES'",(fyid,)).fetchone()[0]
 con.execute("UPDATE account_values SET amount=?,source_type='BANK_IMPORT' WHERE financial_year_id=? AND field_key='Sales'",(sales,fyid)); con.execute("UPDATE account_values SET amount=?,source_type='BANK_IMPORT' WHERE financial_year_id=? AND field_key='Purchases'",(purchases,fyid)); con.execute("UPDATE financial_years SET updated_at=? WHERE id=?",(datetime.utcnow().isoformat(),fyid)); con.commit(); con.close(); flash(f'Applied Bank Review totals: Sales ₹{sales:,.2f}, Purchases ₹{purchases:,.2f}.'); return redirect(url_for('itr.year',fyid=fyid))
@itr.route('/year/<int:fyid>/next',methods=['POST'])
def next_year(fyid):
 con=db(); old=con.execute('SELECT * FROM financial_years WHERE id=?',(fyid,)).fetchone()
 if not old:con.close(); return 'Year not found',404
 y=int(old['financial_year'][:4])+1; fy=f'{y}-{str(y+1)[-2:]}'; now=datetime.utcnow().isoformat()
 try:
  cur=con.execute('INSERT INTO financial_years(client_id,financial_year,status,created_at,updated_at) VALUES(?,?,"projected",?,?)',(old['client_id'],fy,now,now)); new_id=cur.lastrowid; create_values_from_previous(con,new_id,fyid,old['client_id']); con.commit()
 except sqlite3.IntegrityError:new_id=con.execute('SELECT id FROM financial_years WHERE client_id=? AND financial_year=?',(old['client_id'],fy)).fetchone()['id']
 con.close(); return redirect(url_for('itr.year',fyid=new_id))
