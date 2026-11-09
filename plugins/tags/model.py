"""The vocabulary of a tagged table, and the resolver that turns names into tags.

A table whose vocabulary takes the `TagVocabulary` mixin accepts names in its
RefSet field: `[3, 7, "PEACH"]` links tags 3 and 7 and the tag named peach,
whatever its case, creating it when it does not exist yet.
"""
from sqlalchemy import event, select

from kitebase import access
from kitebase.i18n import _
from kitebase.refsets import register_resolver
from kitebase.transforms import ValidationError


def clean_name(name):
    """The name as stored: spaces trimmed at the ends and collapsed inside."""
    return ' '.join(str(name).split())


def name_key(name):
    """The name as compared: case, `_` and `-` make no difference.

    Italian literature, italian_literature and Italian-literature are one tag.
    """
    return clean_name(str(name).replace('_', ' ').replace('-', ' ')).casefold()


def name_error(name):
    """Why a name cannot be a tag, or None.

    The comma separates tags wherever a list is written as text (the widget, an
    import): a tag holding one could be neither typed nor read back.
    """
    if not clean_name(name):
        return _('A tag needs a name')
    if ',' in str(name):
        return _('A tag name cannot contain a comma')
    return None


class TagVocabulary:
    """Mixin of a tag vocabulary: keeps `name` clean and `name_key` in step with it."""


@event.listens_for(TagVocabulary, 'before_insert', propagate=True)
@event.listens_for(TagVocabulary, 'before_update', propagate=True)
def _keep_the_key(mapper, connection, target):
    error = name_error(target.name or '')
    if error:
        raise ValidationError({'name': error})
    target.name = clean_name(target.name)
    target.name_key = name_key(target.name)


class TagNames:
    """Resolver of the RefSets whose target is a tag vocabulary (kitebase.refsets)."""

    @staticmethod
    def applies_to(target_class):
        return issubclass(target_class, TagVocabulary)

    @staticmethod
    def resolve(session, target_class, ref, values):
        for value in values:
            if isinstance(value, str) and clean_name(value) and name_error(value):
                raise ValidationError({ref.name: name_error(value)})
        names = {name_key(v): v for v in values if isinstance(v, str) and name_key(v)}
        found = {}
        if names:
            query = select(target_class).where(target_class.name_key.in_(list(names)))
            found = {tag.name_key: tag.id for tag in session.scalars(query)}

        missing = [key for key in names if key not in found]
        if missing and not access.can(f'{target_class.__name__}.create'):
            raise ValidationError({ref.name: _('You may not create new tags')})
        for key in missing:
            tag = target_class(name=names[key])
            session.add(tag)
            session.flush()
            found[key] = tag.id

        keys = []
        for value in values:
            if isinstance(value, str):
                if name_key(value):
                    keys.append(found[name_key(value)])
            else:
                keys.append(value)
        return keys


register_resolver(TagNames)
