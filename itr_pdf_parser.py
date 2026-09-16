import re
from difflib import SequenceMatcher, get_close_matches

import pdfplumber


# Internal keys are unique across statements so P&L and Balance Sheet fields
# with the same display name never overwrite one another.
FIELD_DEFS = {
    "TRADING": [
        ("trading_opening_stock", "Opening Stock"),
        ("trading_purchases", "Purchases"),
        ("trading_direct_expenses", "Direct Expenses"),
        ("trading_sales", "Sales"),
        ("trading_commission_discounts", "Commission / Discounts"),
        ("trading_closing_stock", "Closing Stock"),
        ("trading_gross_profit", "Gross Profit"),
    ],
    "P&L": [
        ("pnl_gross_profit", "Gross Profit"),
        ("pnl_salary", "Salary"),
        ("pnl_rent", "Rent"),
        ("pnl_electricity", "Electricity Charges"),
        ("pnl_telephone", "Telephone Expenses"),
        ("pnl_repairs", "Repairs & Maintenance"),
        ("pnl_miscellaneous", "Miscellaneous Expenses"),
        ("pnl_depreciation", "Depreciation"),
        ("pnl_interest", "Interest"),
        ("pnl_other_expenses", "Other Expenses"),
        ("pnl_net_profit", "Net Profit"),
    ],
    "BALANCE_SHEET": [
        ("bs_capital", "Capital Account"),
        ("bs_fixed_assets", "Fixed Assets"),
        ("bs_depreciation", "Depreciation"),
        ("bs_investments", "Investments"),
        ("bs_loan", "Loan"),
        ("bs_advances", "Advance / Deposits & Advances"),
        ("bs_closing_stock", "Closing Stock"),
        ("bs_debtors", "Debtors"),
        ("bs_creditors", "Creditors"),
        ("bs_bank", "Bank"),
        ("bs_cash", "Cash"),
        ("bs_other_assets", "Other Assets"),
        ("bs_other_liabilities", "Other Liabilities"),
    ],
}

ALL_FIELDS = [(st, key, label) for st, defs in FIELD_DEFS.items() for key, label in defs]
LABELS = {key: label for _, key, label in ALL_FIELDS}

# Common variants seen in client-prepared accounts. Fuzzy matching is only
# used after these explicit variants so unexpected spellings become review items.
VARIANTS = {
    "opening stock": "trading_opening_stock",
    "to opening stock": "trading_opening_stock",
    "purchases": "trading_purchases",
    "to purchases": "trading_purchases",
    "purchases a/c": "trading_purchases",
    "sales": "trading_sales",
    "by sales": "trading_sales",
    "sales a/c": "trading_sales",
    "transport charges": "trading_direct_expenses",
    "travelling transport charges": "trading_direct_expenses",
    "travelling,transport charges": "trading_direct_expenses",
    "travelling, transport charges": "trading_direct_expenses",
    "direct expenses": "trading_direct_expenses",
    "commission / discounts": "trading_commission_discounts",
    "commission discounts": "trading_commission_discounts",
    "closing stock": None,  # statement-specific below
    "by closing stock": None,
    "gross profit": None,
    "gross profit c/d": "trading_gross_profit",
    "gross prafit c/d": "trading_gross_profit",
    "gross profit b/d": "pnl_gross_profit",
    "gross prafit b/d": "pnl_gross_profit",
    "gross prafit": None,
    "salaries": "pnl_salary",
    "salary": "pnl_salary",
    "salaries & wages": "pnl_salary",
    "shop rent": "pnl_rent",
    "rent": "pnl_rent",
    "electricity charges": "pnl_electricity",
    "electricity & fuel charges": "pnl_electricity",
    "electicity & fual charges": "pnl_electricity",
    "telephone expenses": "pnl_telephone",
    "telephone & net charges": "pnl_telephone",
    "telrphone&net charges": "pnl_telephone",
    "repairs & maintenance": "pnl_repairs",
    "shop maintenance": "pnl_repairs",
    "miscellaneous expenses": "pnl_miscellaneous",
    "depreciation": "pnl_depreciation",
    "interest to bank": "pnl_interest",
    "instest to bank": "pnl_interest",
    "interest": "pnl_interest",
    "net profit": "pnl_net_profit",
    "capital account": "bs_capital",
    "capital account of": "bs_capital",
    "furniture": "bs_fixed_assets",
    "funiture": "bs_fixed_assets",
    "refrigerator": "bs_fixed_assets",
    "investments": "bs_investments",
    "immovable property": "bs_investments",
    "loan": "bs_loan",
    "advance": "bs_advances",
    "deposits & advances": "bs_advances",
    "electricity deposit": "bs_advances",
    "debtors": "bs_debtors",
    "creditors": "bs_creditors",
    "bank balance": "bs_bank",
    "cash in hand": "bs_cash",
    "cash in bank & hand": "bs_cash",
}

AMOUNT_RE = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d{1,2})?")
DATE_RE = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b")


def _repair_pdf_token(token):
    """Fix the duplicated-glyph pattern produced by some client PDFs.

    Only collapse a token when every character occurs twice in succession,
    so normal words such as 'Travelling' remain unchanged.
    """
    if len(token) >= 4 and len(token) % 2 == 0:
        if all(token[i] == token[i + 1] for i in range(0, len(token), 2)):
            return token[::2]
    return token


def clean_line(line):
    return " ".join(_repair_pdf_token(t) for t in str(line or "").split())


def clean_amount(text):
    raw = str(text or "").replace(",", "").replace("₹", "").strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _norm_label(label):
    s = clean_line(label).lower().strip()
    s = re.sub(r"^(?:to|by)\s+", "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*[,/&-]\s*", lambda m: m.group(0).strip(), s)
    s = re.sub(r"\s+(?:c/d|b/d)$", "", s)
    s = re.sub(r"\s+@\s*\d+(?:\.\d+)?%", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .:-")
    return s


def _section_for_line(line, current):
    s = clean_line(line).lower()
    if "balance sheet" in s or "balance shet" in s:
        return "BALANCE_SHEET"
    if "profit & loss" in s or "profit and loss" in s or "profit and los" in s:
        return "P&L"
    if "trading account" in s or "trading a/c" in s:
        return "TRADING"
    # Some combined PDFs put the title before the section heading.
    if "trading a/c for" in s:
        return "TRADING"
    return current


def _is_noise_label(label):
    n = _norm_label(label)
    if not n:
        return True
    if n.startswith(("total", "particular", "amount", "liabilities", "assets")):
        return True
    if n in {"fixed assets", "current assets", "investments", "deposits & advances", "capital account"}:
        return n != "capital account"
    if "account for the year" in n or "as on" in n or "assessment year" in n:
        return True
    if DATE_RE.search(n):
        return True
    if n.endswith(":"):
        return True
    return False


def normalize_field(label, statement):
    n = _norm_label(label)
    if not n:
        return None, 0.0

    # Context-sensitive labels.
    if n in {"closing stock", "by closing stock"}:
        return (("trading_closing_stock", 1.0) if statement == "TRADING" else ("bs_closing_stock", 1.0))
    if n in {"gross profit", "gross prafit"}:
        return (("trading_gross_profit", 0.98) if statement == "TRADING" else ("pnl_gross_profit", 0.98))
    if "less: depreciation" in n or n.startswith("depreciation @"):
        return (("bs_depreciation", 0.96) if statement == "BALANCE_SHEET" else ("pnl_depreciation", 0.96))
    if "furniture (net)" in n or "refrigerator (net)" in n:
        return None, 0.0
    if n in {"open plot", "open plot at zaheerabad", "open plot at ismailkhanpet"}:
        return "bs_investments", 0.92
    if n == "p. sowmya" or n.endswith(" - capital") or n.endswith("- capital"):
        if statement == "BALANCE_SHEET":
            return "bs_capital", 0.90

    exact = VARIANTS.get(n)
    if exact:
        if exact.startswith("trading_") and statement != "TRADING":
            return None, 0.0
        if exact.startswith("pnl_") and statement != "P&L":
            return None, 0.0
        if exact.startswith("bs_") and statement != "BALANCE_SHEET":
            return None, 0.0
        return exact, 1.0

    # Fuzzy match against labels that belong to this statement.
    choices = {k: _norm_label(v) for st, k, v in ALL_FIELDS if st == statement}
    match = get_close_matches(n, list(choices.values()), n=1, cutoff=0.78)
    if match:
        matched_text = match[0]
        key = next(k for k, v in choices.items() if v == matched_text)
        score = SequenceMatcher(None, n, matched_text).ratio()
        return key, round(score, 2)
    return None, 0.0


def _looks_like_label(text):
    n = _norm_label(text)
    if _is_noise_label(text):
        return False
    if not re.search(r"[A-Za-z]", n):
        return False
    return True


def _parse_side(side, pending, statement, candidates, source_pdf, bs_context=None):
    side = clean_line(side).strip()
    if not side:
        return bs_context
    side = re.sub(r"^(?:To|By)\s+", "", side, flags=re.I).strip()
    matches = list(AMOUNT_RE.finditer(side))
    if not matches:
        if _looks_like_label(side):
            pending.append((_norm_label(side), statement))
        return bs_context

    for i, m in enumerate(matches):
        before = side[:m.start()].strip(" -:")
        after = side[m.end():].strip(" -:")
        amount = clean_amount(m.group(0))
        # For a multi-column line the text after one amount belongs to the
        # next label, while the text before it belongs to the current label.
        label = before if before else None
        if label and _looks_like_label(label) and not _is_noise_label(label):
            key, conf = normalize_field(label, statement)
            if key:
                candidates.append({"statement_type": statement, "field_key": key,
                                   "field_label": LABELS[key], "amount": amount,
                                   "original_label": label, "confidence": conf,
                                   "source_pdf": source_pdf})
            else:
                # In Balance Sheet, a name immediately before a capital amount
                # is commonly the proprietor/partner name.
                if statement == "BALANCE_SHEET" and bs_context == "capital":
                    key, conf = "bs_capital", 0.86
                    candidates.append({"statement_type": statement, "field_key": key,
                                       "field_label": LABELS[key], "amount": amount,
                                       "original_label": label, "confidence": conf,
                                       "source_pdf": source_pdf})
                elif not _is_noise_label(label):
                    candidates.append({"statement_type": statement, "field_key": "__UNMAPPED__",
                                       "field_label": label, "amount": amount,
                                       "original_label": label, "confidence": 0.0,
                                       "source_pdf": source_pdf})
        else:
            # Amount-only line: pair with the oldest pending label. A None
            # entry is still consumed so totals/net rows do not shift pairing.
            if pending:
                pending_label, pending_statement = pending.pop(0)
                if pending_label:
                    key, conf = normalize_field(pending_label, pending_statement)
                    if key:
                        candidates.append({"statement_type": pending_statement, "field_key": key,
                                           "field_label": LABELS[key], "amount": amount,
                                           "original_label": pending_label, "confidence": conf,
                                           "source_pdf": source_pdf})
                    elif not _is_noise_label(pending_label):
                        candidates.append({"statement_type": pending_statement, "field_key": "__UNMAPPED__",
                                           "field_label": pending_label, "amount": amount,
                                           "original_label": pending_label, "confidence": 0.0,
                                           "source_pdf": source_pdf})
        if after and i == len(matches) - 1 and _looks_like_label(after):
            pending.append((_norm_label(after), statement))

    return bs_context


def parse_plbs_pdf(file_path, pdf_password=None):
    """Return detected PL/BS fields plus unmapped review items."""
    candidates = []
    pending = {"TRADING": [], "P&L": [], "BALANCE_SHEET": []}
    statement = None
    bs_context = None

    passwords = []
    if pdf_password:
        passwords.append(pdf_password)
    passwords += [None, "", "password", "123456", "bank"]
    pdf = None
    for pwd in passwords:
        try:
            pdf = pdfplumber.open(file_path, password=pwd)
            break
        except Exception:
            pdf = None
    if pdf is None:
        return {"error": "PDF is password protected. Please provide the password."}

    try:
        with pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for raw in text.splitlines():
                    line = clean_line(raw)
                    if not line:
                        continue
                    statement = _section_for_line(line, statement)
                    low = line.lower()
                    if statement == "BALANCE_SHEET":
                        if "capital account" in low:
                            bs_context = "capital"
                        elif "fixed assets" in low:
                            bs_context = "fixed_assets"
                        elif "investments" in low or "immovable property" in low:
                            bs_context = "investments"
                        elif "deposits & advances" in low:
                            bs_context = "advances"

                    if "total" in low and len(AMOUNT_RE.findall(line)):
                        # Consume no pending item for totals; they are not
                        # accounting fields to import.
                        continue
                    if statement is None:
                        continue

                    # Combined Trading/P&L rows often have both debit and
                    # credit columns. Split on By so each side has one label.
                    sides = re.split(r"\bBy\s+|\bBY\s+", line)
                    if len(sides) > 1:
                        # First side is debit; subsequent side is credit.
                        _parse_side(sides[0], pending[statement], statement, candidates, file_path, bs_context)
                        for side in sides[1:]:
                            _parse_side(side, pending[statement], statement, candidates, file_path, bs_context)
                    else:
                        _parse_side(line, pending[statement], statement, candidates, file_path, bs_context)

            # Any remaining pending labels are unresolved and should not be
            # silently turned into zero values.
            for st, items in pending.items():
                for label, _ in items:
                    if label and not _is_noise_label(label):
                        candidates.append({"statement_type": st, "field_key": "__UNMAPPED__",
                                           "field_label": label, "amount": 0.0,
                                           "original_label": label, "confidence": 0.0,
                                           "source_pdf": file_path})
    except Exception as exc:
        return {"error": str(exc)}

    # Aggregate duplicate standard fields within the same PDF. This keeps
    # Furniture + Refrigerator in Fixed Assets without overwriting either.
    aggregated = {}
    unmapped = []
    for item in candidates:
        if item["field_key"] == "__UNMAPPED__":
            unmapped.append(item)
            continue
        key = (item["statement_type"], item["field_key"])
        if key not in aggregated:
            aggregated[key] = dict(item)
        else:
            aggregated[key]["amount"] += item["amount"]
            aggregated[key]["confidence"] = min(aggregated[key]["confidence"], item["confidence"])
            aggregated[key]["original_label"] += "; " + item["original_label"]

    result = list(aggregated.values())
    result.sort(key=lambda x: (x["statement_type"], x["field_label"]))
    return {"fields": result, "unmapped": unmapped}


def fields_for_statement(statement):
    return [{"field_key": key, "field_label": label} for key, label in FIELD_DEFS[statement]]
