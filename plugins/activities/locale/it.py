from kitebase.i18n import register_translations

register_translations('it', {
    # The tables and their columns, as the forms and Tables show them
    'Activity':                 'Attività',
    'Activity type':            'Tipo di attività',
    'Activity link':            'Collegamento di attività',
    'Type':                     'Tipo',
    'Assigned to':              'Assegnata a',
    'Written by':               'Scritta da',
    'Start':                    'Inizio',
    'End':                      'Fine',
    'Due':                      'Scadenza',
    'Done':                     'Fatta il',
    'Priority':                 'Priorità',
    'Source':                   'Origine',
    'Icon':                     'Icona',
    'Role':                     'Ruolo',
    'Record':                   'Record',
    'Table':                    'Tabella',
    # The types the plugin registers
    'Note':                     'Nota',
    'Call':                     'Chiamata',
    'Meeting':                  'Appuntamento',
    'Email':                    'Email',
    'To do':                    'Da fare',
    'Unknown activity type: {code}': 'Tipo di attività sconosciuto: {code}',
    'The priority is a whole number from {low} to {high}': 'La priorità è un numero intero da {low} a {high}',
    'No activity {id}':         'Attività {id} non trovata',
    "'model' and 'id' name the record": "'model' e 'id' indicano il record",
    'An activity needs a type and a subject': "Un'attività ha bisogno di un tipo e di un oggetto",
    'With no date an activity is a fact: give it a date to make it to do':
        "Senza data un'attività è un fatto: dalle una data per renderla da fare",
    "'date' is the new day, as YYYY-MM-DD": "'date' è il nuovo giorno, come AAAA-MM-GG",
    'A done activity is not postponed': "Un'attività fatta non si rimanda",
    'Offered':                  'Proposto',
    'No user {id}':             'Utente {id} non trovato',
    "'state' is todo, done or all": "'state' è todo, done o all",
    'A record is a model and an id, not {ref}': 'Un record è un modello e un id, non {ref}',
    # A move through the states of a record (moves.py)
    'From {old} to {new}':      'Da {old} a {new}',
    'none':                     'nessuno',
})
