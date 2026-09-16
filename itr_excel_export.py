import re
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side
from flask import send_file, abort

def register(itr):
    @itr.route('/year/<int:fyid>/excel')
    def export_year_excel(fyid):
        from itr_manager import db, get_values, calculate_statements
        con=db(); fy=con.execute('SELECT f.*,c.client_name,c.proprietor_name,c.address,c.pan FROM financial_years f JOIN clients c ON c.id=f.client_id WHERE f.id=?',(fyid,)).fetchone()
        if not fy: con.close(); abort(404)
        calculate_statements(con,fyid); rows=get_values(con,fyid); v={r['field_key']:float(r['amount'] or 0) for r in rows}; con.commit(); con.close()
        wb=Workbook(); ws=wb.active; ws.title='Financial Statements'; thin=Side(style='thin',color='808080')
        ws['A1']=fy['client_name'] or ''; ws['A1'].font=Font(bold=True,size=14); ws['A2']=fy['address'] or ''; ws['A3']='PAN'; ws['B3']=fy['pan'] or ''; ws['A4']='Assessment Year'; ws['B4']=fy['financial_year'] or ''
        ws['A6']='Partners'; ws['A6'].font=Font(bold=True); ws['A7']='Partner Name'; ws['B7']='Share %'; ws['A7'].font=ws['B7'].font=Font(bold=True); prop=fy['proprietor_name'] or fy['client_name'] or ''; ws['A8']=prop; ws['B8']='100%'
        ws['A11']='Trading Account'; ws['A11'].font=Font(bold=True); ws['A12']='Particulars'; ws['B12']='Amount'; ws['A12'].font=ws['B12'].font=Font(bold=True)
        for r,label,key in [(13,'Sales','Sales'),(14,'Opening Stock','Opening Stock'),(15,'Purchases','Purchases'),(16,'Closing Stock','Closing Stock'),(17,'Gross Profit','Gross Profit')]: ws.cell(r,1).value=label; ws.cell(r,2).value=v.get(key,0)
        ws['A19']='Profit & Loss Account'; ws['A19'].font=Font(bold=True); ws['A20']='Particulars'; ws['B20']='Amount'; ws['A20'].font=ws['B20'].font=Font(bold=True)
        pnl=[(21,'Gross Profit',None),(22,'Rent','Rent'),(23,'Salary','Salary'),(24,'Telephone','Telephone Expenses'),(25,'Printing & Stationery',None),(26,'Maintenance','Repairs & Maintenance'),(27,'Travel & Transport',None),(28,'Other Expenses',None),(29,'Net Profit',None)]
        for r,label,key in pnl:
            ws.cell(r,1).value=label
            if r==21: ws.cell(r,2).value='=B17'
            elif r==29: ws.cell(r,2).value='=B21-SUM(B22:B28)'
            elif r==28: ws.cell(r,2).value=v.get('Miscellaneous Expenses',0)+v.get('Other Expenses',0)
            else: ws.cell(r,2).value=v.get(key,0) if key else 0
        ws['A31']='Balance Sheet - Assets'; ws['A31'].font=Font(bold=True); ws['A32']='Particulars'; ws['B32']='Amount'; ws['A32'].font=ws['B32'].font=Font(bold=True)
        for r,label,key in [(33,'Closing Stock','Closing Stock'),(34,'Cash in Hand','Cash'),(35,'Bank Balance','Bank'),(36,'Sundry Debtors','Debtors'),(37,'Fixed Assets','Fixed Assets'),(38,'Other Assets','Other Assets')]: ws.cell(r,1).value=label; ws.cell(r,2).value=v.get(key,0)
        ws['A39']='TOTAL ASSETS'; ws['B39']='=SUM(B33:B38)'
        ws['A41']='Balance Sheet - Liabilities'; ws['A41'].font=Font(bold=True); ws['A42']='Particulars'; ws['B42']='Amount'; ws['A42'].font=ws['B42'].font=Font(bold=True)
        ws['A43']='Partners Capital - '+prop; ws['B43']=v.get('Capital Account',0); ws['A44']='Current Year Profit'; ws['B44']='=B29'; ws['A45']='Sundry Creditors'; ws['B45']=v.get('Creditors',0); ws['A46']='Loans'; ws['B46']=v.get('Loan',0); ws['A47']='Other Liabilities'; ws['B47']=v.get('Other Liabilities',0); ws['A48']='TOTAL LIABILITIES'; ws['B48']='=SUM(B43:B47)'; ws['A49']='BALANCE SHEET DIFFERENCE'; ws['B49']='=B39-B48'
        ws['D6']='Calculation / Source Notes'; ws['D6'].font=Font(bold=True); ws['D7']='Direct Expenses / Transport'; ws['E7']=v.get('Direct Expenses',0); ws['D8']='Commission / Discounts'; ws['E8']=v.get('Commission / Discounts',0); ws['D9']='Depreciation'; ws['E9']=v.get('Depreciation',0); ws['D10']='Interest'; ws['E10']=v.get('Interest',0); ws['D11']='Gross Profit Formula'; ws['E11']='=B13+B16+E8-B14-B15-E7'; ws['D12']='Net Profit Formula'; ws['E12']='=B21-SUM(B22:B28)'; ws['D13']='Note'; ws['E13']='Transport is included in Trading direct expenses; not deducted again in P&L.'
        for row in ws.iter_rows(min_row=1,max_row=49,min_col=1,max_col=5):
            for c in row: c.alignment=Alignment(vertical='center',wrap_text=True); c.number_format='#,##0.00' if c.column in (2,5) and isinstance(c.value,(int,float)) else c.number_format
        for r in (6,11,19,31,41):
            for c in range(1,3): ws.cell(r,c).fill='D9EAF7'
        for r in (7,12,20,32,42):
            for c in range(1,3): ws.cell(r,c).fill='EAF2F8'; ws.cell(r,c).border=Border(bottom=thin)
        for r in (17,29,39,48,49):
            for c in range(1,3): ws.cell(r,c).border=Border(top=thin); ws.cell(r,c).font=Font(bold=True)
        ws.column_dimensions['A'].width=36; ws.column_dimensions['B'].width=18; ws.column_dimensions['C'].width=3; ws.column_dimensions['D'].width=30; ws.column_dimensions['E'].width=42; ws.freeze_panes='A12'; ws.sheet_view.showGridLines=False; ws.page_setup.orientation='portrait'; ws.page_setup.fitToWidth=1; ws.sheet_properties.pageSetUpPr.fitToPage=True; ws.print_area='A1:E49'
        out=BytesIO(); wb.save(out); out.seek(0); name=re.sub(r'[^A-Za-z0-9._-]+','_',str(fy['client_name'] or 'Client'))
        return send_file(out,as_attachment=True,download_name=f'{name}_ITR_{fy["financial_year"]}.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    return export_year_excel
