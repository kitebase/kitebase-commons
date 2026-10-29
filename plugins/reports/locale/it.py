from kitebase.i18n import register_translations

register_translations('it', {
    'Print': 'Stampa',
    'Nothing to print here': 'Niente da stampare qui',
    'No rows to print': 'Nessuna riga da stampare',
    'ids must be a list': 'ids deve essere una lista',
    "Unknown report: '{report}'": "Stampa sconosciuta: '{report}'",
    "Unknown report format: '{format}'": "Formato di stampa sconosciuto: '{format}'",
    "You cannot print '{report}': it needs {permission}":
        "Non puoi stampare '{report}': serve {permission}",
    "Report '{report}' has no template": "La stampa '{report}' non ha tracciati",
    "'{template}' is not a template of report '{report}'":
        "'{template}' non è un tracciato della stampa '{report}'",
    "The options form '{form}' of report '{report}' does not exist":
        "La form delle opzioni '{form}' della stampa '{report}' non esiste",
    "The option '{name}' of report '{report}' uses a reserved name":
        "L'opzione '{name}' della stampa '{report}' usa un nome riservato",

    # The labels of the YAML
    'Template': 'Tracciato',
    'Title': 'Titolo',
    'Output': 'Destinazione',
    'Preview (PDF)': 'Anteprima (PDF)',
    'Spreadsheet (Excel)': 'Foglio di calcolo (Excel)',
})
