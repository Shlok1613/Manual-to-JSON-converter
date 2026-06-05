import openpyxl
# Check generated structure around DIP changes
wb = openpyxl.load_workbook('outputs/test_v5/v5test_MAG03D0424.xlsx', data_only=True)
ws = wb['MAG03D0424']
for row in ws.iter_rows(min_row=1, max_row=200, max_col=13, values_only=False):
    name_f = row[5].value  # col F
    name_h = row[7].value  # col H
    if name_f:
        r = row[0].row
        settings = row[6].value or ''  # col G
        v = name_h or ''
        print(f'R{r}: F={name_f} | G={settings} | H={v}')
    elif name_h:
        r = row[0].row
        print(f'R{r}: H={name_h}')
