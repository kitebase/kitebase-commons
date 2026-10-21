"""The phone book of the partners: the demo's report, and the smallest example
of one. The loop reads the records and emits the bands; the template
(andrep/phonebook.json) decides what each band shows. Its spreadsheet is a
plain table, written by a post-processor instead of one row per band."""
from andrep import AndRepRenderer

from reports.registry import load_records, report, report_post


class PhonebookRenderer(AndRepRenderer):
    def on_init(self):
        self.count = 0

    def on_after_band(self, band_name):
        if band_name == 'band':
            self.count += 1


@report('demo_ui.phonebook', table='Partner', label='Phone book', renderer=PhonebookRenderer)
def phonebook(r, params):
    for row in load_records('Partner', params['ids']):
        r.emit('band')
    r.emit('totals')


@report_post('demo_ui.phonebook', format='xlsx')
def phonebook_sheet(records, book):
    """One contact per row under a header: the detail bands, in the order of
    the template's cells, and nothing of the page."""
    sheet = book.active
    sheet.title = 'Contacts'
    sheet.append(['Name', 'City', 'Phone', 'Email'])
    for record in records:
        if record['band'] == 'band':
            sheet.append(record['values'])
