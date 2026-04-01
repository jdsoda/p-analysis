import os, json, tempfile, gc
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, send_file, flash)
from werkzeug.utils import secure_filename

# ── Config ──────────────────────────────────────────────
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'CA@2024')
SECRET_KEY   = os.environ.get('SECRET_KEY',   'panalysis-secret-2024')
MAX_MB       = 20

app = Flask(__name__)
app.secret_key      = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_MB * 1024 * 1024

UPLOAD_FOLDER = tempfile.gettempdir()

# ── Auth decorator ───────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('auth'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ── Routes ───────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def login():
    if session.get('auth'):
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        if request.form.get('password') == APP_PASSWORD:
            session['auth'] = True
            return redirect(url_for('dashboard'))
        error = "Incorrect password. Please try again."
    return render_template('login.html', error=error,
                           timeout=request.args.get('timeout'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    results    = []
    error_msg  = None
    summary    = {}

    if request.method == 'POST':
        pdf = request.files.get('pdf_file')
        pdf_password = request.form.get('pdf_password', '').strip() or None
        if not pdf or pdf.filename == '':
            error_msg = "Please select a PDF file."
        else:
            fname  = secure_filename(pdf.filename)
            target = os.path.join(UPLOAD_FOLDER, fname)
            pdf.save(target)

            try:
                import sys
                sys.path.insert(0, os.path.dirname(__file__))
                from analyze import run_analysis
                results = run_analysis(target, pdf_password)
                gc.collect()
                if isinstance(results, list) and results:
                    # Store in session as JSON string (keep it small)
                    session['results']  = json.dumps(results)
                    session['pdf_name'] = os.path.splitext(fname)[0]
                elif isinstance(results, dict) and 'error' in results:
                    error_msg = "Analysis error: " + results['error']
            except Exception as e:
                error_msg = f"Error: {str(e)}"
            finally:
                try: os.remove(target)
                except: pass

    # Re-load previous session results
    elif session.get('results'):
        try:
            results = json.loads(session['results'])
        except Exception:
            results = []

    if results:
        summary = {
            'total_parties': len(results),
            'total_txns':    sum(int(r.get('count', 0)) for r in results),
            'total_debit':   sum(float(r.get('total_debit',  0)) for r in results),
            'total_credit':  sum(float(r.get('total_credit', 0)) for r in results),
            'flagged_count': sum(1 for r in results if r.get('flags')),
        }

    return render_template('dashboard.html',
                           results=results,
                           summary=summary,
                           error_msg=error_msg,
                           pdf_name=session.get('pdf_name', ''))

@app.route('/download-excel')
@login_required
def download_excel():
    raw = session.get('results')
    if not raw:
        flash("No results to export. Please analyze a statement first.")
        return redirect(url_for('dashboard'))

    try:
        results   = json.loads(raw)
        json_path = os.path.join(UPLOAD_FOLDER, f'panalysis_{os.getpid()}.json')
        xlsx_path = os.path.join(UPLOAD_FOLDER, f'panalysis_{os.getpid()}.xlsx')
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
        for p in [json_path]:
            try: os.remove(p)
            except: pass

# ── Run ──────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
