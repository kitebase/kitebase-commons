# crm

A light CRM: opportunities moving through the stages of a pipeline, won or
lost, with the activities that tell their story, and the campaigns that bring
them. Light on purpose: it grows when there are users asking, not before.

It depends on `partners` and `activities`; `smtp` is optional. Like the rest of
the commons it is menu-silent: it draws pages and commands, and the
application puts them in its menu. The demo does it in `demo_crm`.

## The model

- **Opportunity**: a real negotiation, someone showed interest. Not one per
  contact: a board full of cards stuck at the first stage says nothing, and the
  figures become false. It always has a partner, a pipeline and a stage; an
  amount, an expected closing, a salesperson (whoever writes it, unless someone
  else is named), a priority from 0 to 3, and where it came from (a campaign).
- **Pipeline**: a kind of negotiation and the stages it goes through. Most
  businesses need one; the renewals of contracts beside new customers are two,
  each with stages of its own.
- **Stage**: a step of a pipeline, in the order the board shows them. Free: an
  opportunity passes from any stage to any other. `folded` starts the column
  folded on the board, for the stages seldom used.
- **Outcome**: `open`, `won` or `lost`. A closed opportunity keeps the stage it
  closed in, so the lost ones say where they were lost; `closed_at` follows the
  outcome. `LostReason` is a table, since the lost are most of the data and the
  reason is what the figures count.
- **Campaign**: an initiative that brings opportunities, a new product
  presented, a fair, a mailing. Its members are not a table: they are the
  partners its activities reached.

An activity on an opportunity reaches its partner (`activities.follow`), so the
history of the partner holds the negotiation.

Computed in the query that loads a list (`model.py`), so a list shows them
like any column:

- on an opportunity, **the next thing to do**: `next_activity`, `next_due`, and
  `next_state` (`overdue`, `today`, `planned`, `none`), which the card shows as a
  coloured ribbon. Nothing planned is a negotiation going cold;
- on a campaign, **what it brought**: `contacted`, `to_handle` (contacts still to
  do), `opportunity_count`, `won_count`, `won_amount`.

## The rules (rules.py)

On every port that writes an opportunity:

- with no pipeline, the first active one; with no stage, the first of its
  pipeline. The form leaves both optional for this reason;
- a stage of another pipeline is refused, except when the pipeline is what
  changed: then it starts again from the first stage of the new one;
- the priority stays in 0..3, the outcome in its three values.

**The story of the negotiation.** A stage changed and a closing are written as
done activities of the type `stage`: "From Qualified to Proposal", "Lost:
Price". Moves made close together by the same person are one line: a card tried
in two columns leaves "From A to C", and one moved back where it was leaves
nothing. Closings are never merged. Dragging never closes: winning and losing
are commands.

## The pages (pages.yaml)

- `opportunity_list`: every opportunity, closed ones included, with the story of
  the row clicked on the right. It switches to the board.
- `opportunity_board`: the same rows on a board, the stages of one pipeline at a
  time, picked above it. It opens on the open ones of whoever opens it, two
  rules the user sees and may take away to look at a colleague's board or at
  everyone's. Each column shows its count and the total of the amounts.
- `opportunity_form`: the opportunity, with its activities in a section: an
  opportunity lives a short time and has few, born mostly on the board. (For a
  partner the history stays beside the list: it grows for years.)
- `pipeline_form`: a pipeline and its stages, moved by hand.
- `campaign_list`: the campaigns with their figures; on the right the
  opportunities each one brought, below its history.

The commands of the opportunities, on the list and the board alike:

| Command | What it does |
|---|---|
| Won (`w`) | closes it won |
| Lost (`l`) | asks why, from the lost reasons, and closes it lost |
| Open again | back to open |
| Plan an activity (`p`) | a short dialog: type, subject, due date, note |
| Hand to another salesperson | the ticked opportunities, or the one under the cursor |
| Write an email (`e`), Email sent | only where the application loads smtp |

## From the partners, and the campaigns

The plugin adds two commands to every list of partners, through the partners
plugin's view `partner_table` (merged by `id`):

- **New opportunity** (`o`), on the row: the form, with the partner filled in.
  The campaign is chosen there, never guessed;
- **Contact for a campaign**, on the ticked partners or the one under the
  cursor: campaign, type, subject, due date, note. It writes one activity per
  partner, linked to the campaign too, all or none.

A contact **starts to do** (the due date starts from today): the campaign is a
list of work, and a contact stays open until it has its outcome. Emptied, the
date records a contact already done, a letter sent.

In the history of a campaign, a contact still to do has **Create opportunity**:
the partner and the campaign are the activity's own links, the activity becomes
done and is linked to the new opportunity, whose story starts from it, and the
opportunity opens to be completed. "Not interested" is marking it done. The
command is declared by the campaign's page only: the history of a partner, or
the mail sent, has none.

## Email (mail.py, with smtp)

Where the application loads `smtp` (`optional: smtp: [mail]`), an opportunity
is written to at the addresses of its partner, as smtp knows them
(`register_addresses_via`). A message sent becomes an activity of the
opportunity where activities bridges smtp, so it is in the story of the
negotiation and in the history of the partner. Without smtp the module stays
dormant and the commands leave the view by themselves.

## Who sees what

Two different things, both without code:

- **seeing only one's own by default**: the board's rule on the salesperson,
  which the user may take away;
- **not being able to see the others'**: a grant with a condition on the role,
  for instance with outside agents:

```yaml
# role salesperson
- Opportunity.read:   { where: { user_id: $ctx.id } }
- Opportunity.update: { where: { user_id: $ctx.id } }
# role supervisor
- Opportunity.read
- Opportunity.update
```

Working on a colleague's negotiations is signed by whoever does it: there is
no switching user. Activities for a colleague are assigned to them, and someone
who leaves hands their opportunities over.

## The standard pipeline

The plugin ships no rows. `crm.api.make_pipeline(session)` writes the standard
pipeline (New, Qualified, Proposal, Negotiation) in the language of the
application, only where there is no pipeline at all; with a name and stages it
writes another:

```python
from crm.api import make_pipeline

make_pipeline(session)
make_pipeline(session, "Renewals", ["Expiring", "Proposal sent", "Signed"])
```

The demo's seed (`demo/kite.py`) calls it, with a second pipeline, some lost
reasons and a few opportunities to look at.

## Not here yet

- **Figures over time**: won and lost by period, the lost reasons, the value by
  stage. The data is there; the summary will come from the groups of DataView.
- **Leads coming in** from a web form or an email: a new partner and an
  opportunity at the first stage, when there are gateways.
- **Reminders that arrive by themselves**, and sending a campaign in bulk: they
  wait for jobs.
- **Product lines** on an opportunity and on a campaign: a module joining crm
  and products, when there are products.
