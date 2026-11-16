from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import object_session

import kitebase.utils
from kitebase import apptime


def _tables():
    """Activity and ActivityLink, the models of the activities plugin: this
    module is a mixin of the generated model, which defines them."""
    models = kitebase.utils.get_app().models
    return models['Activity'], models['ActivityLink']


def _when(Activity):
    """The day an activity is due: its due date, else the day it starts."""
    return func.coalesce(Activity.due_date, func.date(Activity.start_at))


class Opportunity:
    """The next thing to do on the negotiation, read in the query that loads
    the list: the activity still to do that comes first, by its due date or the
    day it starts, its day, and how that day stands against today. A board
    shows it on the card; nothing planned is a negotiation going cold.
    """

    @classmethod
    def _next(cls, column):
        """`column(Activity)` of the first activity still to do on the opportunity."""
        Activity, Link = _tables()
        return (select(column(Activity))
                .select_from(Activity)
                .join(Link, Link.activity_id == Activity.id)
                .where(Link.model == 'Opportunity', Link.record_id == cast(cls.id, String),
                       Activity.done_at.is_(None))
                .order_by(_when(Activity), Activity.id)
                .limit(1)
                .correlate(cls)
                .scalar_subquery())

    def _read(self, name):
        session = object_session(self)
        if session is None or self.id is None:
            return None
        cls = type(self)
        return session.scalar(select(getattr(cls, name)).where(cls.id == self.id))

    @hybrid_property
    def next_activity(self):
        return self._read('next_activity')

    @next_activity.expression
    def next_activity(cls):
        return cls._next(lambda Activity: Activity.subject)

    @hybrid_property
    def next_due(self):
        return self._read('next_due')

    @next_due.expression
    def next_due(cls):
        return cls._next(_when)

    # Today is the organisation's (kitebase.apptime), read each time a query
    # is built: a list loaded tomorrow says tomorrow's overdue.
    @hybrid_property
    def next_state(self):
        return self._read('next_state')

    @next_state.expression
    def next_state(cls):
        due = cls._next(_when)
        today = apptime.today().isoformat()
        return case((due.is_(None), 'none'), (due < today, 'overdue'),
                    (due == today, 'today'), else_='planned')
