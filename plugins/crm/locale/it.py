from kitebase.i18n import register_translations

register_translations('it', {
    # The tables and their columns, as the forms and Tables show them
    'Opportunity':              'Opportunità',
    'Opportunities':            'Opportunità',
    'Opportunity board':        'Bacheca delle opportunità',
    'Pipeline':                 'Pipeline',
    'Stage':                    'Fase',
    'Stages':                   'Fasi',
    'Lost reason':              'Motivo della perdita',
    'Reason':                   'Motivo',
    'Campaign':                 'Campagna',
    'Partner':                  'Partner',
    'Salesperson':              'Commerciale',
    'Expected amount':          'Valore atteso',
    'Expected closing':         'Chiusura prevista',
    'Priority':                 'Priorità',
    'Outcome':                  'Esito',
    'Closed on':                'Chiusa il',
    'Why it was lost':          'Perché è stata persa',
    'Description':              'Descrizione',
    'Folded':                   'Chiusa',
    'Name':                     'Nome',
    'Sequence':                 'Ordine',
    'From':                     'Dal',
    'To':                       'Al',
    'Normal':                   'Normale',
    'Open':                     'Aperta',
    'Won':                      'Vinta',
    'Lost':                     'Persa',
    # The standard pipeline (api.make_pipeline), written in the app's language
    'Sales':                    'Vendite',
    'New':                      'Nuova',
    'Qualified':                'Qualificata',
    'Proposal':                 'Offerta',
    'Negotiation':              'Trattativa',
    # The rules
    'There is no pipeline yet: create one with its stages first':
        'Non c\'è ancora una pipeline: creane una con le sue fasi',
    'The stage is not one of the pipeline chosen':
        'La fase non è della pipeline scelta',
    'The pipeline has no stages yet':
        'La pipeline non ha ancora fasi',
    'The priority is a whole number from {low} to {high}':
        'La priorità è un numero intero da {low} a {high}',
    'The outcome is one of: {values}':
        'L\'esito è uno fra: {values}',
})
