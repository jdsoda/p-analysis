import pdfplumber
import json
import sys
import re
from collections import defaultdict

# ─────────────────────────────────────────────
# Amount cleaner – removes ₹, commas, spaces
# ─────────────────────────────────────────────
def clean_amount(val):
    if val is None:
        return 0.0
    num_str = re.sub(r'[^\d.]', '', str(val).strip())
    try:
        return float(num_str) if num_str else 0.0
    except ValueError:
        return 0.0

# ─────────────────────────────────────────────
# Party name cleaner – strips ref numbers,
# dates, UPI IDs to get the real party name
# ─────────────────────────────────────────────
def extract_party(narration: str) -> str:
    if not narration:
        return "UNKNOWN"
    
    # Uppercase & strip
    s = narration.upper().strip()
    
    # Remove common bank prefixes
    prefixes = [
        r'^NEFT[-/]?\s*', r'^RTGS[-/]?\s*', r'^IMPS[-/]?\s*',
        r'^UPI[-/]?\s*', r'^CHQ[-/]?\s*', r'^ATM[-/]?\s*',
        r'^CASH[-/]?\s*', r'^INT\.?\s*', r'^TRF[-/]?\s*',
        r'^BY TRANSFER[-/]?\s*', r'^TO TRANSFER[-/]?\s*',
        r'^INF[-/]?\s*', r'^ACH[-/]?\s*', r'^ECS[-/]?\s*',
    ]
    for p in prefixes:
        s = re.sub(p, '', s, flags=re.IGNORECASE).strip()

    # Remove trailing ref numbers / dates / 12-digit numbers
    s = re.sub(r'\b\d{9,}\b', '', s)        # long numeric refs
    s = re.sub(r'\d{2}[-/]\d{2}[-/]\d{2,4}', '', s)  # dates
    s = re.sub(r'\s{2,}', ' ', s).strip()

    # Take first meaningful segment (split on / or -)
    for sep in ['/', ' - ', '|']:
        parts = s.split(sep)
        candidate = parts[0].strip()
        if len(candidate) > 3:
            s = candidate
            break

    # Remove trailing special chars
    s = re.sub(r'[^A-Z0-9 &\.]+$', '', s).strip()
    
    return s if len(s) > 2 else narration.upper().strip()[:40]


# ─────────────────────────────────────────────
# Auto-detect column indices from header row
# ─────────────────────────────────────────────
def detect_columns(header_row):
    """
    Returns dict: {date, narration, ref, debit, credit, balance}
    with column indices. Falls back to common defaults.
    """
    cols = {
        'date': 0, 'narration': 1, 'ref': 2,
        'debit': 3, 'credit': 4, 'balance': 5
    }
    if not header_row:
        return cols

    mapping = {
        'date':      ['date', 'txn date', 'value date', 'post date', 'trans date'],
        'narration': ['narration', 'description', 'particulars', 'remarks', 'details', 'transaction details'],
        'ref':       ['ref', 'ref no', 'chq no', 'cheque no', 'reference', 'chq/ref'],
        'debit':     ['debit', 'dr', 'withdrawal', 'withdrawals', 'debit amount'],
        'credit':    ['credit', 'cr', 'deposit', 'deposits', 'credit amount'],
        'balance':   ['balance', 'bal', 'running bal', 'closing bal'],
    }

    for idx, cell in enumerate(header_row):
        if cell is None:
            continue
        cell_lower = str(cell).lower().strip()
        for field, keywords in mapping.items():
            if any(kw in cell_lower for kw in keywords):
                cols[field] = idx
                break

    return cols


# ─────────────────────────────────────────────
# Audit flag logic (for IT / GST audit use)
# ─────────────────────────────────────────────
IT_THRESHOLD  = 200000   # ₹2 Lakh – reportable single txn
SFT_THRESHOLD = 1000000  # ₹10 Lakh – SFT cash deposit limit

def get_audit_flags(party_data: dict) -> list:
    flags = []
    net    = party_data['net']
    total_debit  = party_data['total_debit']
    total_credit = party_data['total_credit']
    count  = party_data['count']
    max_single = party_data['max_single_txn']

    # Cheque / payment returned
    if abs(net) < 0.01 and count > 1:
        flags.append("CHEQUE RETURNED / REVERSED")

    # High-value single transaction
    if max_single >= IT_THRESHOLD:
        flags.append(f"HIGH VALUE TXN ≥₹{IT_THRESHOLD//1000}K")

    # Large aggregate credit (cash SFT)
    if total_credit >= SFT_THRESHOLD:
        flags.append("AGGREGATE CREDIT ≥₹10L")

    # Round-figure suspicion (multiple round txns)
    if party_data['round_fig_count'] >= 2:
        flags.append("ROUND FIGURE TRANSACTIONS")

    # Frequent transactions with same party
    if count >= 10:
        flags.append(f"FREQUENT PARTY ({count} entries)")

    return flags


# ─────────────────────────────────────────────
# Main analysis
# ─────────────────────────────────────────────
def run_analysis(file_path, pdf_password=None):
    all_rows  = []
    col_map   = None

    # Common bank PDF passwords to try automatically
    auto_passwords = ['', pdf_password] if pdf_password else ['']
    # Add common patterns
    auto_passwords += ['password', '123456', 'bank']

    opened_pdf = None
    for pwd in auto_passwords:
        if pwd is None:
            continue
        try:
            opened_pdf = pdfplumber.open(file_path, password=pwd)
            # Test if we can read it
            _ = opened_pdf.pages[0]
            break
        except Exception:
            opened_pdf = None
            continue

    if opened_pdf is None:
        return [{"error": "PDF is password protected. Please provide the password."}]

    try:
        with opened_pdf as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if not table:
                    continue

                # Detect columns from first non-empty row that looks like a header
                if col_map is None:
                    for row in table[:5]:
                        if row and any(
                            str(c).lower().strip() in
                            ['date','narration','debit','credit','description','particulars']
                            for c in row if c
                        ):
                            col_map = detect_columns(row)
                            break

                for row in table:
                    if not row or len([c for c in row if c]) < 3:
                        continue
                    all_rows.append(row)

    except Exception as e:
        return [{"error": str(e)}]

    if not all_rows:
        return []

    if col_map is None:
        col_map = {'date': 0, 'narration': 1, 'ref': 2, 'debit': 3, 'credit': 4, 'balance': 5}

    # ── Aggregate party-wise ──
    parties = defaultdict(lambda: {
        'party': '',
        'count': 0,
        'total_debit': 0.0,
        'total_credit': 0.0,
        'net': 0.0,
        'max_single_txn': 0.0,
        'round_fig_count': 0,
        'transactions': []
    })

    SKIP_PATTERNS = re.compile(
        r'^(date|narration|description|particulars|debit|credit|balance|ref|slno|sr\.|#)',
        re.IGNORECASE
    )

    for row in all_rows:
        try:
            max_idx = len(row) - 1

            narration_raw = str(row[col_map['narration']] or '') if col_map['narration'] <= max_idx else ''
            if not narration_raw or SKIP_PATTERNS.match(narration_raw.strip()):
                continue

            debit  = clean_amount(row[col_map['debit']]  if col_map['debit']  <= max_idx else None)
            credit = clean_amount(row[col_map['credit']] if col_map['credit'] <= max_idx else None)

            # Skip rows with no money movement
            if debit == 0 and credit == 0:
                continue

            party_key = extract_party(narration_raw)
            p = parties[party_key]
            p['party']        = party_key
            p['count']       += 1
            p['total_debit'] += debit
            p['total_credit']+= credit
            p['net']         += (credit - debit)

            single_amount = max(debit, credit)
            if single_amount > p['max_single_txn']:
                p['max_single_txn'] = single_amount

            # Round figure check (multiple of 1000 and >= 10000)
            if single_amount >= 10000 and single_amount % 1000 == 0:
                p['round_fig_count'] += 1

        except Exception:
            continue

    # ── Build output list ──
    output = []
    for key, p in parties.items():
        flags = get_audit_flags(p)
        output.append({
            'party':         p['party'],
            'count':         p['count'],
            'total_debit':   round(p['total_debit'],  2),
            'total_credit':  round(p['total_credit'], 2),
            'net':           round(p['net'],           2),
            'max_single':    round(p['max_single_txn'],2),
            'flags':         flags,
            'flag_count':    len(flags),
        })

    # Sort: flagged first, then by total volume
    output.sort(key=lambda x: (-x['flag_count'], -(x['total_debit'] + x['total_credit'])))
    return output


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = run_analysis(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"error": "No file path provided"}))
