from kitebase.i18n import register_translations

register_translations('it', {
    'A list of role codes is expected, such as ["library.desk"]':
        'Serve una lista di codici di ruolo, come ["library.desk"]',
    'Unknown role: {codes}': 'Ruolo sconosciuto: {codes}',
    'A list of signed permissions is expected, such as ["+Book.read"]':
        'Serve una lista di permessi con segno, come ["+Book.read"]',
    'Not a signed permission: {codes}': 'Non è un permesso con segno: {codes}',

    # The labels of the YAML
    'Roles': 'Ruoli',
    'Access exceptions': 'Eccezioni di accesso',
    'Access': 'Accesso',
    'As text': 'Come testo',
    'Role codes, as JSON': 'Codici dei ruoli, in JSON',
    'What this user may do': 'Cosa può fare questo utente',
    'Exceptions, as JSON': 'Eccezioni, in JSON',
    ('The roles give the cells; a click forces one for this user alone, '
     'granted (+) or denied (-). A denial wins over the roles.'):
        ('I ruoli danno le celle; un clic ne forza una per questo solo utente, '
         'concessa (+) o negata (-). Una negazione vince sui ruoli.'),
    'A role brings the roles it implies, shown checked and greyed.':
        'Un ruolo porta con sé i ruoli che implica, mostrati spuntati e in grigio.',
})
