"""commons demo harness — loads the shared plugins and exercises them.

Slim analogue of kitebase's devtest.py: loads the plugin root, computes the DB
schema, regenerates model.py, initialises the sqlite DB and runs a smoke test.

Run from this directory:  uv run kite.py
Its commands, through the kitebase CLI:  kitebase check, kitebase db-check, ...
"""
import kitebase
import kitebase.utils


def setup(generate: bool = True):
    """Load plugins, compute schema, register behaviors, (re)generate model.py."""
    app = kitebase.utils.get_app().declare("config.yaml")

    # Commons Archivable query behavior — injected, core stays agnostic (GL-19).
    from common.model import Archivable  # type: ignore
    app.add_query_behavior(Archivable)

    if generate:
        print("Generated model.py" if app.generate() else "model.py up to date.")

    return app, app.plugins


def seed(app, model):
    """Fill an empty database with what the demo needs in order to show something.

    Development data, not a mechanism: every table is filled only while it is
    empty, so whatever is entered from the UI is left alone. Dev credentials are
    admin/admin.
    """
    with app.get_session() as session:
        if not session.query(model.User).first():
            session.add(model.User(
                name="Administrator",
                username="admin",
                password="admin",
                email="admin@example.com",
                is_admin=True,
                # The account of secrets.example/smtp.yaml: admin writes to the partners
                mail_accounts=["office"],
            ))

        # The role codes belong to the application: the Customers and Suppliers
        # views filter on C and S and stamp them on what is added there.
        if not session.query(model.PartnerRole).first():
            session.add_all([
                model.PartnerRole(id="C", label="Customer", sequence=10),
                model.PartnerRole(id="S", label="Supplier", sequence=20),
            ])

        # The functions of a contact: who, inside a partner, the technical
        # documents and the invoices go to
        if not session.query(model.PartnerFunction).first():
            session.add_all([
                model.PartnerFunction(id="TEC", label="Technical office", sequence=10),
                model.PartnerFunction(id="ADM", label="Accounts", sequence=20),
                model.PartnerFunction(id="WHS", label="Warehouse", sequence=30),
            ])

        if not session.query(model.Partner).first():
            session.add_all([
                model.Partner(kind="person", name="Smith, John", roles=["C"],
                              city="Bristol", email="john@example.com"),
                model.Partner(kind="organization", name="Riverside Hardware Ltd",
                              roles=["S"], city="Leeds"),
                # Both at once — the case that makes one table worth having.
                # With contacts holding functions: a technical document reaches
                # Ross, an invoice reaches White.
                model.Partner(kind="organization", name="Northwind Trading",
                              roles=["C", "S"], city="Hull", email="info@northwind.example",
                              children=[
                                  model.Partner(kind="person", usage="contact",
                                                name="Ross, Mark", email="ross@northwind.example",
                                                functions=["TEC", "WHS"]),
                                  model.Partner(kind="person", usage="contact",
                                                name="White, Anna", email="white@northwind.example",
                                                functions=["ADM"]),
                              ]),
                # No role yet: reachable only from the unfiltered list, which is
                # where a subject is promoted to customer or supplier.
                model.Partner(kind="person", name="Doe, Jane", city="York"),
            ])

        session.flush()
        seed_crm(session, model)
        seed_projects(session, model)
        seed_time(session, model)
        session.commit()


def seed_crm(session, model):
    """A few opportunities to look at, on the two pipelines of the plugin's
    seed (sales, and the renewals of the contracts)."""
    if session.query(model.Opportunity).first():
        return
    pipelines = [r[0] for r in session.query(model.Pipeline.id).order_by(model.Pipeline.sequence)]
    if len(pipelines) < 2:
        return
    sales, renewals = pipelines[:2]

    def stages(pipeline_id):
        return session.query(model.Stage).filter_by(pipeline_id=pipeline_id) \
            .order_by(model.Stage.sequence).all()

    sales_stages, renewal_stages = stages(sales), stages(renewals)
    by_name = {p.name: p.id for p in session.query(model.Partner)
               .filter(model.Partner.parent_id.is_(None))}
    admin = session.query(model.User).filter_by(username="admin").first()
    for name, partner, pipeline, stage, amount in (
            ("New shelving for the shop", "Smith, John", sales, sales_stages[0], 1800),
            ("Warehouse racking", "Northwind Trading", sales, sales_stages[2], 12500),
            ("Seasonal stock", "Doe, Jane", sales, sales_stages[1], 950),
            ("Maintenance contract 2027", "Northwind Trading", renewals,
             renewal_stages[0], 4200)):
        session.add(model.Opportunity(
            name=name, partner_id=by_name[partner], pipeline_id=pipeline,
            stage_id=stage.id, amount=amount, user_id=admin.id if admin else None))


def seed_projects(session, model):
    """A few projects to look at: one for a customer, one internal, and a
    typical job to copy. Admin is a person too, so that "My tasks" shows
    something."""
    if session.query(model.Project).first():
        return
    from projects.api import add_stages  # type: ignore

    admin = session.query(model.User).filter_by(username="admin").first()
    if admin is not None and admin.partner_id is None:
        me = model.Partner(kind="person", name="Carter, Alex", city="York",
                           email="alex@example.com")
        session.add(me)
        session.flush()
        admin.partner_id = me.id
    people = {p.name: p.id for p in session.query(model.Partner)
              .filter(model.Partner.kind == "person")}
    northwind = session.query(model.Partner).filter_by(name="Northwind Trading").first()

    def project(name, state, partner=None, template=False, tasks=()):
        row = model.Project(name=name, state=state, is_template=template,
                            partner_id=partner.id if partner else None,
                            manager_id=people.get("Carter, Alex"))
        session.add(row)
        session.flush()
        add_stages(session, row.id)
        stages = session.query(model.TaskStage).filter_by(project_id=row.id) \
            .order_by(model.TaskStage.sequence).all()
        for place, (task, stage, who, estimate) in enumerate(tasks, 1):
            session.add(model.Task(name=task, project_id=row.id, stage_id=stages[stage].id,
                                   assignee_id=people.get(who), estimate_hours=estimate,
                                   sequence=place))

    project("Warehouse racking install", "active", northwind, tasks=(
        ("Survey of the warehouse", 3, "Ross, Mark", 4),
        ("Layout drawing", 1, "Carter, Alex", 6),
        ("Order the uprights", 0, "Carter, Alex", 1),
        ("Install and test", 0, None, 16)))
    project("Move to the new office", "planned", tasks=(
        ("Choose the movers", 0, "Carter, Alex", 2),
        ("Network and phones", 0, None, 8)))
    project("Standard racking install", "planned", template=True, tasks=(
        ("Survey of the site", 0, None, 4),
        ("Layout drawing", 0, None, 6),
        ("Order the material", 0, None, 1),
        ("Install and test", 0, None, 16)))


def seed_time(session, model):
    """A few hours on the warehouse project, on its tasks and on the project as
    a whole, so that the timesheet and the figures show something."""
    if session.query(model.TimeEntry).first():
        return
    project = session.query(model.Project).filter_by(name="Warehouse racking install").first()
    if project is None:
        return
    tasks = {t.name: t.id for t in session.query(model.Task).filter_by(project_id=project.id)}
    people = {p.name: p.id for p in session.query(model.Partner)
              .filter(model.Partner.kind == "person")}
    import datetime
    for day, task, who, hours, note in (
            (datetime.date(2026, 11, 16), "Survey of the warehouse", "Ross, Mark", 3.5, None),
            (datetime.date(2026, 11, 18), "Layout drawing", "Carter, Alex", 2.0, "First draft"),
            (datetime.date(2026, 11, 20), "Layout drawing", "Carter, Alex", 1.5, None),
            (datetime.date(2026, 11, 20), None, "Carter, Alex", 0.5, "Call with the customer")):
        if who not in people:
            continue
        session.add(model.TimeEntry(project_id=project.id, task_id=tasks.get(task),
                                    worker_id=people[who], date=day, hours=hours, note=note))


def main():
    app, plugins = setup()

    import model  # type: ignore  # generated
    app.open(model)
    seed(app, model)

    print(f"Plugins loaded: {', '.join(plugins.sorted)}")
    print(f"Tables: {', '.join(sorted(app.tables.keys()))}")

    with app.get_session() as session:
        for user in session.query(model.User).all():
            print(f"User {user.id}: {user.username} <{user.email}> admin={user.is_admin}")

    print("commons demo smoke OK")


if __name__ == "__main__":
    from pathlib import Path

    from kitebase.cli import DB_COMMANDS, make_parser, run_cli

    args = make_parser().parse_args()

    if args.command in DB_COMMANDS:
        # These look at the database as it is: no create_all, no startup check:
        # reporting the difference is the whole point.
        app, plugins = setup()
        import model  # type: ignore  # generated by setup()

        app.open(model, create_all=False, check_schema=False)
        run_cli(app, args, output_dir=Path("data"))
    elif args.command:
        app, _ = setup(generate=False)
        run_cli(app, args, output_dir=Path("data"))
    else:
        main()
