"""The phone book of the partners: the demo's report, and the smallest example
of one. The loop reads the records and emits the bands; the template
(andrep/phonebook.json) decides what each band shows."""
from andrep import AndRepRenderer

from reports.registry import load_records, report


class PhonebookRenderer(AndRepRenderer):
    def on_init(self):
        self.count = 0

    def on_after_band(self, band_name):
        if band_name == 'row':
            self.count += 1


@report('demo_ui.phonebook', renderer=PhonebookRenderer)
def phonebook(r, params):
    for row in load_records('Partner', params['ids']):
        r.emit('row')
    r.emit('totals')
