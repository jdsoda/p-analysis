import os, json, tempfile, gc, hashlib
from functools import wraps
from datetime import datetime
from flask import (Flask, render_template, request, redirect,
                   url_for, session, send_file, flash)
from werkzeug.utils import secure_filename

# ── Config ──────────────────────────────────────────────
SECRET_KEY = os.environ.get('SECRET_KEY', 'panalysis-secret-2024')
MAX_MB     = 20
MAX_HISTORY = 5

# ── Multi-CA Users (Environment Variable గా set చేయవచ్చు)
# Format: "username1:password1,username2:password2"
# Default: single CA@2024 password (backward compatible)
def get_users():
    users_env = os.environ.get('CA_USERS', '')
    users = {}
    if users_env:
        for entry in users_env.split(','):
            parts = entry.strip().split(':', 1)
            if len(parts) == 2:
                users[parts[0].strip()] = parts[1].strip()
    if not users:
        # Fallback to old single password
        pwd = os.environ.get('APP_PASSWORD', 'CA@2024')
        users['admin'] = pwd
    return users

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_MB * 1024 * 1024
UPLOAD_FOLDER = tempfile.gettempdir()

# ── Auth ─────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('auth'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── History helpers ──────────────────────────────────────
def get_history():
    try:
        return json.loads(session.get('history', '[]'))
    except:
        return []

def add_to_history(name, results, summary):
    history = get_history()
    entry = {
        'id':       hashlib.md5(f"{name}{datetime.now()}".encode()).hexdigest()[:8],
        'name':     name,
        'date':     datetime.now().strftime('%d-%b-%Y %H:%M'),
        'parties':  summary.get('total_parties', 0),
        'flagged':  summary.get('flagged_count', 0),
        'debit':    summary.get('total_debit', 0),
        'credit':   summary.get('total_credit', 0),
        'results':  results
    }
    # Add to front, keep only last 5
    history.insert(0, entry)
    history = history[:MAX_HISTORY]
    # Store without results to save session space, results stored separately
    history_meta = [{k: v for k, v in h.items() if k != 'results'} for h in history]
    session['history'] = json.dumps(history_meta)
    # Store results per id
    session[f"res_{entry['id']}"] = json.dumps(results)
    return entry['id']

def build_summary(results):
    return {
        'total_parties': len(results),
        'total_txns':    sum(int(r.get('count', 0)) for r in results),
        'total_debit':   sum(float(r.get('total_debit',  0)) for r in results),
        'total_credit':  sum(float(r.get('total_credit', 0)) for r in results),
        'flagged_count': sum(1 for r in results if r.get('flags')),
    }

# ── Routes ───────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def login():
    if session.get('auth'):
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        uname = request.form.get('username', '').strip()
        pwd   = request.form.get('password', '').strip()
        users = get_users()
        if uname in users and users[uname] == pwd:
            session['auth']     = True
            session['username'] = uname
            return redirect(url_for('dashboard'))
        error = "Incorrect username or password."
    return render_template('login.html', error=error,
                           timeout=request.args.get('timeout'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    results   = []
    error_msg = None
    summary   = {}
    active_id = session.get('active_id', '')
    pdf_name  = session.get('pdf_name', '')

    if request.method == 'POST':
        pdfs         = request.files.getlist('pdf_file')
        pdf_password = request.form.get('pdf_password', '').strip() or None
        client_name  = request.form.get('client_name', '').strip()
        all_results  = []
        errors       = []

        for pdf in pdfs:
            if not pdf or pdf.filename == '':
                continue
            fname  = secure_filename(pdf.filename)
            target = os.path.join(UPLOAD_FOLDER, fname)
            pdf.save(target)
            try:
                import sys
                sys.path.insert(0, os.path.dirname(__file__))
                from analyze import run_analysis
                res = run_analysis(target, pdf_password)
                gc.collect()
                if isinstance(res, list):
                    all_results.extend(res)
                elif isinstance(res, dict) and 'error' in res:
                    errors.append(f"{fname}: {res['error']}")
            except Exception as e:
                errors.append(f"{fname}: {str(e)}")
            finally:
                try: os.remove(target)
                except: pass

        if errors:
            error_msg = " | ".join(errors)

        if all_results:
            # Merge duplicate parties across multiple PDFs
            merged = {}
            for r in all_results:
                key = r.get('party', '')
                if key in merged:
                    merged[key]['count']        += r.get('count', 0)
                    merged[key]['total_debit']  += r.get('total_debit', 0)
                    merged[key]['total_credit'] += r.get('total_credit', 0)
                    merged[key]['net']          += r.get('net', 0)
                    merged[key]['max_single']    = max(merged[key]['max_single'], r.get('max_single', 0))
                    merged[key]['flags']         = list(set(merged[key]['flags'] + r.get('flags', [])))
                    merged[key]['flag_count']    = len(merged[key]['flags'])
                else:
                    merged[key] = dict(r)
            results  = sorted(merged.values(), key=lambda x: -(x.get('flag_count', 0)))
            summary  = build_summary(results)
            display_name = client_name or (pdfs[0].filename if pdfs else 'Statement')
            display_name = os.path.splitext(display_name)[0]
            active_id = add_to_history(display_name, results, summary)
            session['active_id'] = active_id
            session['pdf_name']  = display_name
            session['results']   = json.dumps(results)

    # Load from history if switching
    load_id = request.args.get('load')
    if load_id:
        raw = session.get(f'res_{load_id}')
        if raw:
            results  = json.loads(raw)
            summary  = build_summary(results)
            active_id = load_id
            session['active_id'] = load_id
            session['results']   = raw
            # Find name from history
            for h in get_history():
                if h['id'] == load_id:
                    session['pdf_name'] = h['name']
                    pdf_name = h['name']
                    break

    # Re-load current results
    elif not results and session.get('results'):
        try:
            results = json.loads(session['results'])
            summary = build_summary(results)
        except:
            results = []

    return render_template('dashboard.html',
                           results=results,
                           summary=summary,
                           error_msg=error_msg,
                           pdf_name=session.get('pdf_name', ''),
                           history=get_history(),
                           active_id=active_id,
                           username=session.get('username', 'CA'))

@app.route('/download-excel')
@login_required
def download_excel():
    raw = session.get('results')
    if not raw:
        flash("No results to export.")
        return redirect(url_for('dashboard'))
    try:
        results   = json.loads(raw)
        json_path = os.path.join(UPLOAD_FOLDER, f'pa_{os.getpid()}.json')
        xlsx_path = os.path.join(UPLOAD_FOLDER, f'pa_{os.getpid()}.xlsx')
        pdf_name  = session.get('pdf_name', 'Statement')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False)
        from export import run_export
        run_export(json_path, xlsx_path, pdf_name)
        gc.collect()
        fname = f"P-Analysis_{pdf_name}.xlsx"
        return send_file(xlsx_path, as_attachment=True,
                         download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f"Excel export failed: {str(e)}")
        return redirect(url_for('dashboard'))
    finally:
        try: os.remove(json_path)
        except: pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
