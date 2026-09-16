from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from flask import send_file, abort


def register_excel_route(itr_blueprint):
    @itr_blueprint.route('/year/<int:fyid>/excel')
    def export_year_excel(fyid):
        from itr_manager import db, get_values, calculate_statements

        con = db()
        fy = con.execute(
            '''SELECT f.*, c.client_name, c.proprietor_name, c.address, c.pan, c.business_type
               FROM financial_years f JOIN clients c ON c.id=f.client_id WHERE f.id=?''',
            (fyid,)
        ).fetchone()
        if not fy:
            con.close()
            abort(404)

        calculate_statements(con, fyid)
        rows = get_values(con, fyid)
        values = {r['field_key']: float(r['amount'] or 0) for r in rows}
        con.commit()
        con.close()

        wb = Workbook()
        ws = wb.active
        ws.title = 'Financial Statements'

        thin = Side(style='thin', color='808080')
        section_fill = 'D9EAF7'
        header_fill = 'EAF2F8'

        ws['A1'] = fy['client_name'] or ''
        ws['A1'].font = Font(bold=True, size=14)
        ws['A2'] = fy['address'] or ''
        ws['A3'] = 'PAN'
        ws['B3'] = fy['pan'] or ''
        ws['A4'] = 'Assessment Year'
        ws['B4'] = fy['financial_year'] or ''

        # Same section order and naming style as the NEELAGI SANGAMESH reference model.
        ws['A6'] = 'Partners'
        ws['A6'].font = Font(bold=True)
        ws['A7'] = 'Partner Name'
        ws['B7'] = 'Share %'
        ws['A7'].font = ws['B7'].font = Font(bold=True)
        proprietor = fy['proprietor_name'] or fy['client_name'] or ''
        ws['A8'] = proprietor
        ws['B8'] = '100%'

        # Trading Account
        ws['A11'] = 'Trading Account'
        ws['A11'].font = Font(bold=True)
        ws['A12'] = 'Particulars'
        ws['B12'] = 'Amount'
        ws['A12'].font = ws['B12'].font = Font(bold=True)
        trading_rows = [
            (13, 'Sales', 'Sales'),
            (14, 'Opening Stock', 'Opening Stock'),
            (15, 'Purchases', 'Purchases'),
            (16, 'Closing Stock', 'Closing Stock'),
            (17, 'Gross Profit', 'Gross Profit'),
        ]
        for r, label, key in trading_rows:
            ws.cell(r, 1).value = label
            ws.cell(r, 2).value = values.get(key, 0)
        # Direct expense/transport is kept in the Trading calculation without changing the reference row order.
        # It is disclosed in a note below the statement.

        # P&L
        ws['A19'] = 'Profit & Loss Account'
        ws['A19'].font = Font(bold=True)
        ws['A20'] = 'Particulars'
        ws['B20'] = 'Amount'
        ws['A20'].font = ws['B20'].font = Font(bold=True)
        pnl_rows = [
            (21, 'Gross Profit', 'Gross Profit'),
            (22, 'Rent', 'Rent'),
            (23, 'Salary', 'Salary'),
            (24, 'Telephone', 'Telephone Expenses'),
            (25, 'Printing & Stationery', 'Other Expenses'),
            (26, 'Maintenance', 'Repairs & Maintenance'),
            (27, 'Travel & Transport', 'Direct Expenses'),
            (28, 'Other Expenses', 'Miscellaneous Expenses'),
            (29, 'Net Profit', 'Net Profit'),
        ]
        for r, label, key in pnl_rows:
            ws.cell(r, 1).value = label
            if label == 'Gross Profit':
                ws.cell(r, 2).value = '=B17'
            elif label == 'Net Profit':
                ws.cell(r, 2).value = '=B21-SUM(B22:B28)'
            else:
                ws.cell(r, 2).value = values.get(key, 0)

        # Balance Sheet - Assets
        ws['A31'] = 'Balance Sheet - Assets'
        ws['A31'].font = Font(bold=True)
        ws['A32'] = 'Particulars'
        ws['B32'] = 'Amount'
        ws['A32'].font = ws['B32'].font = Font(bold=True)
        assets = [
            (33, 'Closing Stock', 'Closing Stock'),
            (34, 'Cash in Hand', 'Cash'),
            (35, 'Bank Balance', 'Bank'),
            (36, 'Sundry Debtors', 'Debtors'),
            (37, 'Fixed Assets', 'Fixed Assets'),
            (38, 'Other Assets', 'Other Assets'),
        ]
        for r, label, key in assets:
            ws.cell(r, 1).value = label
            ws.cell(r, 2).value = values.get(key, 0)
        ws['A39'] = 'TOTAL ASSETS'
        ws['B39'] = '=SUM(B33:B38)'
        ws['A39'].font = ws['B39'].font = Font(bold=True)

        # Balance Sheet - Liabilities
        ws['A41'] = 'Balance Sheet - Liabilities'
        ws['A41'].font = Font(bold=True)
        ws['A42'] = 'Particulars'
        ws['B42'] = 'Amount'
        ws['A42'].font = ws['B42'].font = Font(bold=True)
        liabilities = [
            (43, 'Partners Capital - ' + proprietor, 'Capital Account'),
            (44, 'Current Year Profit', 'Net Profit'),
            (45, 'Sundry Creditors', 'Creditors'),
            (46, 'Loans', 'Loan'),
            (47, 'Other Liabilities', 'Other Liabilities'),
        ]
        for r, label, key in liabilities:
            ws.cell(r, 1).value = label
            ws.cell(r, 2).value = '=B29' if label == 'Current Year Profit' else values.get(key, 0)
        ws['A48'] = 'TOTAL LIABILITIES'
        ws['B48'] = '=SUM(B43:B47)'
        ws['A49'] = 'BALANCE SHEET DIFFERENCE'
        ws['B49'] = '=B39-B48'
        ws['A48'].font = ws['B48'].font = ws['A49'].font = ws['B49'].font = Font(bold=True)

        # Source/calculation notes, without altering the reference statement layout.
        ws['D6'] = 'Calculation / Source Notes'
        ws['D6'].font = Font(bold=True)
        ws['D7'] = 'Direct Expenses / Transport'
        ws['E7'] = values.get('Direct Expenses', 0)
        ws['D8'] = 'Commission / Discounts'
        ws['E8'] = values.get('Commission / Discounts', 0)
        ws['D9'] = 'Depreciation'
        ws['E9'] = values.get('Depreciation', 0)
        ws['D10'] = 'Interest'
        ws['E10'] = values.get('Interest', 0)
        ws['D11'] = 'Other Expenses'
        ws['E11'] = values.get('Other Expenses', 0)
        ws['D12'] = 'Formula: Gross Profit'
        ws['E12'] = '=B13+B16+B8-B14-B15-E7'
        ws['D13'] = 'Formula: Net Profit'
        ws['E13'] = '=B21-SUM(B22:B28)'

        # Styling: professional, simple, and compatible with older Excel versions.
        for row in ws.iter_rows(min_row=1, max_row=49, min_col=1, max_col=5):
            for cell in row:
                cell.alignment = Alignment(vertical='center')
                if cell.column in (2, 5) and isinstance(cell.value, (int, float)):
                    cell.number_format = '#,##0.00'
        for r in (6, 11, 19, 31, 41):
            for c in range(1, 3):
                ws.cell(r, c).fill = section_fill
        for r in (7, 12, 20, 32, 42):
            for c in range(1, 3):
                ws.cell(r, c).fill = header_fill
                ws.cell(r, c).border = Border(bottom=thin)
        for r in (17, 29, 39, 48, 49):
            for c in range(1, 3):
                ws.cell(r, c).border = Border(top=thin)
        ws.column_dimensions['A'].width = 34
        ws.column_dimensions['B'].width = 18
        ws.column_dimensions['C'].width = 3
        ws.column_dimensions['D'].width = 28
        ws.column_dimensions['E'].width = 18
        ws.freeze_panes = 'A12'
        ws.sheet_view.showGridLines = False
        ws.page_setup.orientation = 'portrait'
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_area = 'A1:E49'

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', str(fy['client_name'] or 'Client'))
        return send_file(output, as_attachment=True,
                         download_name=f'{safe_name}_ITR_{fy["financial_year"]}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    return export_year_excel
