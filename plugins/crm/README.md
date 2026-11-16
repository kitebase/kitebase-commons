# crm

A light CRM: opportunities moving through the stages of a pipeline, won or
lost, with the activities that tell their story. Light on purpose: it grows when
there are users asking, not before.

## The model

- **Opportunity**: a real negotiation, someone showed interest. Not one per
  contact: a board full of cards stuck at the first stage says nothing. It
  always has a partner, a pipeline and a stage; an amount, an expected closing,
  a salesperson, a priority from 0 to 3, and where it came from (a campaign).
- **Pipeline**: a kind of negotiation and the stages it goes through. Most
  businesses need one; renewals of contracts beside new customers are two.
- **Stage**: a step of a pipeline. Free: an opportunity passes from any stage to
  any other, the order is how the board shows them. `folded` starts the column
  folded.
- **Outcome**: `open`, `won` or `lost`. A closed opportunity keeps the stage it
  closed in, so the lost ones say where they were lost; `closed_at` follows the
  outcome. `LostReason` is a table, since the lost are most of the data and the
  reason is what the figures count.
- **Campaign**: an initiative that brings opportunities. Its members are the
  partners with an activity linked to it, not a table.

An activity on an opportunity reaches its partner (`activities.follow`), so the
history of the partner holds the negotiation.

## The rules (rules.py)

On every port that writes an opportunity:

- with no pipeline, the first active one; with no stage, the first of its
  pipeline;
- a stage of another pipeline is refused, except when the pipeline is what
  changed: then it starts again from the first stage of the new one;
- the priority stays in 0..3, the outcome in its three values.

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

## Where it surfaces

Menu-silent like the rest of the commons. The plugin draws `opportunity_list`,
`opportunity_form` (the stage offered is one of the opportunity's pipeline) and
`pipeline_form` (its stages, in the order the board shows them); the
application puts them in its menu. The demo does it in `demo_crm`.
