import re
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from flask import send_file, abort


def register(itr):
    @itr.route('/year/<int:fyid>/excel')
    def export_year_excel(fyid):
        from itr_manager import db, get_values, calculate_statements
        con = db()
        fy = con.execute('SELECT f.*,c.client_name,c.proprietor_name,c.address,c.pan,c.business_type FROM financial_years f JOIN clients c ON c.id=f.client_id WHERE f.id=?', (fyid,)).fetchone()
        if not fy:
            con.close()
            abort(404)

        calculate_statements(con, fyid)
        rows = get_values(con, fyid)
        v = {r['field_key']: float(r['amount'] or 0) for r in rows}
        settings = {r['field_key']: r for r in con.execute('SELECT * FROM projection_settings WHERE client_id=?', (fy['client_id'],)).fetchall()}
        con.commit()
        con.close()

        wb = Workbook()
        wb.remove(wb.active)
        thin = Side(style='thin', color='808080')
        header_fill = PatternFill('solid', fgColor='D9EAF7')
        sub_fill = PatternFill('solid', fgColor='EAF2F8')

        def money(ws, cell, value):
            ws[cell] = value
            ws[cell].number_format = '#,##0.00'

        def setup(ws, title, assessment_year, period):
            ws['A1'] = title
            ws['A1'].font = Font(bold=True, size=14)
            ws['A2'] = f"PROP: {fy['proprietor_name'] or fy['client_name'] or ''}"
            ws['A3'] = fy['address'] or ''
            ws['A4'] = f'Assessment Year: {assessment_year}'
            ws['A5'] = period
            ws.sheet_view.showGridLines = False
            ws.freeze_panes = 'A7'
            ws.column_dimensions['A'].width = 38
            ws.column_dimensions['B'].width = 18
            ws.column_dimensions['C'].width = 4
            ws.column_dimensions['D'].width = 38
            ws.column_dimensions['E'].width = 18
            for row in ws.iter_rows(min_row=1, max_row=60, min_col=1, max_col=5):
                for c in row:
                    c.alignment = Alignment(vertical='center', wrap_text=True)

        # 1. GST Reconciliation — same tab structure as the Sangamesh model.
        ws = wb.create_sheet('GST Reconciliation')
        setup(ws, f"{fy['client_name']} — GST RECONCILIATION", fy['financial_year'], '')
        ws['A7'] = 'GST Turnover'; money(ws, 'B7', 0)
        ws['A8'] = 'Books / P&L Sales'; money(ws, 'B8', v.get('Sales', 0))
        ws['A9'] = 'Turnover Difference'; ws['B9'] = '=B7-B8'; ws['B9'].number_format = '#,##0.00'
        ws['A11'] = 'GST Purchases'; money(ws, 'B11', 0)
        ws['A12'] = 'Books / P&L Purchases'; money(ws, 'B12', v.get('Purchases', 0))
        ws['A13'] = 'Purchase Difference'; ws['B13'] = '=B11-B12'; ws['B13'].number_format = '#,##0.00'
        ws['A15'] = 'Note'; ws['B15'] = 'GST figures remain separate from books figures. Enter GST turnover/purchases when available; differences are for reconciliation only and are not posted automatically.'
        ws['A15'].font = Font(bold=True)
        ws.column_dimensions['B'].width = 70

        # 2. Balance Sheet — source/current year model.
        ws = wb.create_sheet('Balance Sheet')
        setup(ws, fy['client_name'], fy['financial_year'], 'Balance Sheet as on 31-03-' + (fy['financial_year'][-4:] if fy['financial_year'] else ''))
        ws['A7'] = 'Liabilities'; ws['B7'] = 'Amount (Rs.)'; ws['D7'] = 'Assets'; ws['E7'] = 'Amount (Rs.)'
        for c in ('A7','B7','D7','E7'): ws[c].font = Font(bold=True); ws[c].fill = header_fill; ws[c].border = Border(bottom=thin)
        ws['A8'] = 'Capital Account'; money(ws, 'B8', v.get('Capital Account', 0))
        if v.get('Creditors', 0): ws['A9'] = 'Creditors'; money(ws, 'B9', v.get('Creditors', 0))
        if v.get('Loan', 0): ws['A10'] = 'Loans'; money(ws, 'B10', v.get('Loan', 0))
        if v.get('Other Liabilities', 0): ws['A11'] = 'Other Liabilities'; money(ws, 'B11', v.get('Other Liabilities', 0))
        ws['A12'] = 'TOTAL LIABILITIES'; ws['B12'] = '=SUM(B8:B11)'; ws['B12'].number_format = '#,##0.00'

        ws['D8'] = 'Fixed Assets'; money(ws, 'E8', v.get('Fixed Assets', 0))
        ws['D9'] = 'Less: Depreciation'; money(ws, 'E9', -abs(v.get('Depreciation', 0)))
        ws['D10'] = 'Fixed Assets (Net)'; ws['E10'] = '=E8+E9'; ws['E10'].number_format = '#,##0.00'
        ws['D12'] = 'Investments'; money(ws, 'E12', v.get('Investments', 0))
        ws['D14'] = 'Deposits & Advances'; money(ws, 'E14', v.get('Advance / Deposits & Advances', 0))
        ws['D16'] = 'Current Assets:'; ws['D16'].font = Font(bold=True); ws['D16'].fill = sub_fill
        ws['D17'] = 'Closing Stock'; money(ws, 'E17', v.get('Closing Stock', 0))
        ws['D18'] = 'Debtors'; money(ws, 'E18', v.get('Debtors', 0))
        ws['D19'] = 'Bank Balance'; money(ws, 'E19', v.get('Bank', 0))
        ws['D20'] = 'Cash in Hand'; money(ws, 'E20', v.get('Cash', 0))
        ws['D21'] = 'Other Assets'; money(ws, 'E21', v.get('Other Assets', 0))
        ws['D23'] = 'TOTAL ASSETS'; ws['E23'] = '=SUM(E10,E12,E14,E17:E21)'; ws['E23'].number_format = '#,##0.00'
        for c in ('A12','B12','D23','E23'):
            ws[c].font = Font(bold=True); ws[c].border = Border(top=thin)

        # 3. Trading and P&L — exact two-sided layout used by the Sangamesh model.
        ws = wb.create_sheet('Trading and PL Account')
        period = f"Trading, Profit & Loss Account for the period 01-04-{fy['financial_year'][:4]} to 31-03-{fy['financial_year'][-4:]}"
        setup(ws, fy['client_name'], fy['financial_year'], period)
        ws['A7'] = 'TRADING ACCOUNT'; ws['A7'].font = Font(bold=True, size=12)
        for cell, val in [('A8','Particulars (Dr.)'),('B8','Amount (Rs.)'),('D8','Particulars (Cr.)'),('E8','Amount (Rs.)')]:
            ws[cell] = val; ws[cell].font = Font(bold=True); ws[cell].fill = header_fill; ws[cell].border = Border(bottom=thin)
        ws['A9']='To Opening Stock'; money(ws,'B9',v.get('Opening Stock',0))
        ws['A10']='To Purchases'; money(ws,'B10',v.get('Purchases',0))
        ws['A11']='To Transport Charges'; money(ws,'B11',v.get('Direct Expenses',0))
        ws['A12']='To Gross Profit c/d'; ws['B12']='=E9+E10-E9*0+B13-B9-B10-B11'; ws['B12']='=E9+E10+B13-B9-B10-B11'; ws['B12'].number_format='#,##0.00'
        ws['D9']='By Sales'; money(ws,'E9',v.get('Sales',0))
        ws['D10']='By Commission / Discounts'; money(ws,'E10',v.get('Commission / Discounts',0))
        ws['D11']='By Closing Stock'; money(ws,'E11',v.get('Closing Stock',0))
        ws['B13']='=SUM(B9:B12)'; ws['E13']='=SUM(E9:E11)'; ws['A13']='TOTAL'; ws['D13']='TOTAL'
        for c in ('A13','B13','D13','E13'): ws[c].font=Font(bold=True); ws[c].border=Border(top=thin); ws[c].number_format='#,##0.00'

        ws['A15']='PROFIT & LOSS ACCOUNT'; ws['A15'].font=Font(bold=True, size=12)
        for cell, val in [('A16','Particulars (Dr.)'),('B16','Amount (Rs.)'),('D16','Particulars (Cr.)'),('E16','Amount (Rs.)')]:
            ws[cell]=val; ws[cell].font=Font(bold=True); ws[cell].fill=header_fill; ws[cell].border=Border(bottom=thin)
        pnl_rows=[('To Salaries & Wages','Salary'),('To Rent','Rent'),('To Electricity Charges','Electricity Charges'),('To Telephone Expenses','Telephone Expenses'),('To Repairs & Maintenance','Repairs & Maintenance'),('To Travelling','Other Expenses'),('To Depreciation','Depreciation')]
        r=17
        for label,key in pnl_rows:
            ws.cell(r,1).value=label; money(ws,f'B{r}',v.get(key,0)); r+=1
        ws['A24']='To Net Profit c/d'; ws['B24']='=E17-SUM(B17:B23)'; ws['B24'].number_format='#,##0.00'
        ws['D17']='By Gross Profit b/d'; ws['E17']='=B12'; ws['E17'].number_format='#,##0.00'
        ws['A25']='TOTAL'; ws['B25']='=SUM(B17:B24)'; ws['D25']='TOTAL'; ws['E25']='=E17'
        for c in ('A25','B25','D25','E25'): ws[c].font=Font(bold=True); ws[c].border=Border(top=thin); ws[c].number_format='#,##0.00'
        ws['A27']=f"Note: Net Profit transferred to Capital Account ({fy['proprietor_name'] or fy['client_name']})."
        ws.merge_cells('A27:E27')

        # 4. Projected Balance Sheet — same layout as Sangamesh model.
        def projected_values():
            out={}
            for key,val in v.items():
                s=settings.get(key); method=s['growth_method'] if s else 'AUTO_GROWTH'; pct=float(s['growth_percent']) if s else 10
                out[key]=val*(1+pct/100) if method=='AUTO_GROWTH' else val
            return out
        pv=projected_values()
        ws=wb.create_sheet('BS Projected 25-26')
        next_ay=''
        m=re.search(r'20(\d{2})[-/](\d{2,4})',fy['financial_year'] or '')
        if m: next_ay=f"20{int(m.group(1))+1:02d}-20{(int(m.group(2)) if len(m.group(2))==4 else 2000+int(m.group(2)))+1:04d}"
        setup(ws, fy['client_name'], next_ay or fy['financial_year'], 'Balance Sheet - Projected')
        ws['A7']='Liabilities'; ws['B7']='Amount (Rs.)'; ws['D7']='Assets'; ws['E7']='Amount (Rs.)'
        for c in ('A7','B7','D7','E7'): ws[c].font=Font(bold=True); ws[c].fill=header_fill
        ws['A8']='Capital Account:'; ws['A9']='  Opening Capital (b/f)'; money(ws,'B9',v.get('Capital Account',0)); ws['A10']='  Add: Net Profit'; ws['B10']='=E18'; ws['B10'].number_format='#,##0.00'; ws['A11']='  Creditors'; money(ws,'B11',pv.get('Creditors',0)); ws['A12']='TOTAL LIABILITIES'; ws['B12']='=SUM(B9:B11)'; ws['B12'].number_format='#,##0.00'
        ws['D8']='Fixed Assets:'; ws['D9']='  Furniture / Fixed Assets (WDV)'; ws['E9']='=MAX(0,B9*0+'+str(pv.get('Fixed Assets',0))+'-'+str(pv.get('Depreciation',0))+')'; ws['E9'].number_format='#,##0.00'; ws['D11']='Investments'; money(ws,'E11',pv.get('Investments',0)); ws['D13']='Deposits & Advances'; money(ws,'E13',pv.get('Advance / Deposits & Advances',0)); ws['D15']='Current Assets:'; ws['D16']='  Closing Stock'; money(ws,'E16',pv.get('Closing Stock',0)); ws['D17']='  Debtors'; money(ws,'E17',pv.get('Debtors',0)); ws['D18']='  Bank Balance'; money(ws,'E18',pv.get('Bank',0)); ws['D19']='  Cash in Hand'; money(ws,'E19',pv.get('Cash',0)); ws['D20']='  Other Assets'; money(ws,'E20',pv.get('Other Assets',0)); ws['D22']='TOTAL ASSETS'; ws['E22']='=SUM(E9,E11,E13,E16:E20)'; ws['E22'].number_format='#,##0.00'

        # 5. Projected Trading-PL — same layout and separate GST-taxable sales lines.
        ws=wb.create_sheet('Trading-PL Projected 25-26')
        setup(ws, fy['client_name'], next_ay or fy['financial_year'], 'Trading, Profit & Loss Account - Projected')
        ws['A7']='TRADING ACCOUNT'; ws['A7'].font=Font(bold=True, size=12)
        for cell,val in [('A8','Particulars (Dr.)'),('B8','Amount (Rs.)'),('D8','Particulars (Cr.)'),('E8','Amount (Rs.)')]: ws[cell]=val; ws[cell].font=Font(bold=True); ws[cell].fill=header_fill
        ws['A9']='To Opening Stock'; money(ws,'B9',pv.get('Opening Stock',0)); ws['A10']='To Purchases'; money(ws,'B10',pv.get('Purchases',0)); ws['A11']='To Transport Charges'; money(ws,'B11',pv.get('Direct Expenses',0)); ws['A12']='To Gross Profit c/d'; ws['B12']='=E9+E10+E11+B13-B9-B10-B11'; ws['B12'].number_format='#,##0.00'
        ws['D9']='By Sales-Taxable (as per GST Turnover)'; money(ws,'E9',pv.get('Sales',0)); ws['D10']='By Sales - GST Exempt / Other'; money(ws,'E10',pv.get('Commission / Discounts',0)); ws['D11']='By Closing Stock'; money(ws,'E11',pv.get('Closing Stock',0)); ws['A13']='TOTAL'; ws['B13']='=SUM(B9:B12)'; ws['D13']='TOTAL'; ws['E13']='=SUM(E9:E11)'
        for c in ('A13','B13','D13','E13'): ws[c].font=Font(bold=True); ws[c].border=Border(top=thin); ws[c].number_format='#,##0.00'
        ws['A15']='PROFIT & LOSS ACCOUNT'; ws['A15'].font=Font(bold=True, size=12)
        for cell,val in [('A16','Particulars (Dr.)'),('B16','Amount (Rs.)'),('D16','Particulars (Cr.)'),('E16','Amount (Rs.)')]: ws[cell]=val; ws[cell].font=Font(bold=True); ws[cell].fill=header_fill
        r=17
        for label,key in pnl_rows:
            ws.cell(r,1).value=label; money(ws,f'B{r}',pv.get(key,0)); r+=1
        ws['A24']='To Net Profit c/d'; ws['B24']='=E17-SUM(B17:B23)'; ws['B24'].number_format='#,##0.00'; ws['D17']='By Gross Profit b/d'; ws['E17']='=B12'; ws['E17'].number_format='#,##0.00'; ws['A25']='TOTAL'; ws['B25']='=SUM(B17:B24)'; ws['D25']='TOTAL'; ws['E25']='=E17'
        for c in ('A25','B25','D25','E25'): ws[c].font=Font(bold=True); ws[c].border=Border(top=thin); ws[c].number_format='#,##0.00'

        for ws in wb.worksheets:
            ws.page_setup.orientation='portrait'
            ws.page_setup.fitToWidth=1
            ws.sheet_properties.pageSetUpPr.fitToPage=True
            ws.print_area=f'A1:E{max(ws.max_row,25)}'
            for row in ws.iter_rows():
                for c in row:
                    if c.column in (2,5) and isinstance(c.value,(int,float)):
                        c.number_format='#,##0.00'

        out=BytesIO()
        wb.save(out)
        out.seek(0)
        name=re.sub(r'[^A-Za-z0-9._-]+','_',str(fy['client_name'] or 'Client'))
        return send_file(out, as_attachment=True, download_name=f'{name}_Sangamesh_Model_{fy["financial_year"]}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    return export_year_excel
