from kitebase.i18n import register_translations

register_translations('it', {
    "No mail account '{name}'": "Nessun account di posta '{name}'",
    "Mail account '{name}': {problem}": "Account di posta '{name}': {problem}",
    'A message sent by the system names its account': "Un messaggio spedito dal sistema indica il suo account",
    'You have no mail account to send from: ask the administrator':
        "Non hai un account di posta da cui spedire: chiedilo all'amministratore",
    "You may not send from the account '{name}'": "Non puoi spedire dall'account '{name}'",
    'A list of account names is expected, such as ["office", "info"]':
        'Serve una lista di nomi di account, come ["office", "info"]',
    'Unknown mail account: {names}': 'Account di posta sconosciuto: {names}',
    "'{field}' is a list of addresses": "'{field}' è una lista di indirizzi",
    "'{value}' in {field} is not an email address": "'{value}' in {field} non è un indirizzo email",
    'A message is a mapping of to, subject, body...': 'Un messaggio è una mappa di to, subject, body...',
    'The message has no recipient': 'Il messaggio non ha destinatari',
    'The message has no subject': "Il messaggio non ha l'oggetto",
    'The subject is one line': "L'oggetto sta su una riga",
    "'links' is a list of {model, id, role}": "'links' è una lista di {model, id, role}",
    "'attachments' is a list": "'attachments' è una lista",
    'The mail server did not take the message: {error}': 'Il server di posta non ha accettato il messaggio: {error}',
    "'message' is a mapping of to, subject, body...": "'message' è una mappa di to, subject, body...",
    "'{ref}' is not a file you attached": "'{ref}' non è un file che hai allegato",
    'An attachment is {ref}, {media} or {name, content}': 'Un allegato è {ref}, {media} oppure {name, content}',
    "Attachments need the media root '{root}' in config.yaml":
        "Gli allegati richiedono la radice media '{root}' in config.yaml",
    'A file is uploaded through the upload route, not the dispatcher':
        'Un file si carica dalla rotta di upload, non dal dispatcher',
    "No {model} {id}": "{model} {id} non trovato",
    "'model' and 'id' name the record": "'model' e 'id' indicano il record",
    'Send email': 'Spedire email',
    'Mail': 'Email',
    'Mail accounts': 'Account di posta',
    'The accounts this user may send email from; the first one is the default.':
        "Gli account da cui l'utente può spedire email; il primo è quello predefinito.",
    'yes': 'sì',
    'no': 'no',
    '{name} is a list of records': '{name} è una lista di record',
    '{name} is a record: name one of its fields': '{name} è un record: indica uno dei suoi campi',
    '{model} has no field {name}': '{model} non ha il campo {name}',
    'no value given for {name}': 'nessun valore per {name}',
    '{name} needs a record': '{name} richiede un record',
    "'{model}' is not a table": "'{model}' non è una tabella",
    'Some placeholders do not resolve: {names}': 'Alcuni segnaposto non si risolvono: {names}',
    "'record' is {model, id}": "'record' è {model, id}",
    "'params' is a mapping of name to value": "'params' è una mappa di nome e valore",
})
