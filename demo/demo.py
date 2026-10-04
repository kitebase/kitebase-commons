"""commons demo harness — loads the shared plugins and exercises them.

Slim analogue of kitebase's devtest.py: loads the plugin root, computes the DB
schema, regenerates model.py, initialises the sqlite DB and runs a smoke test.

Run from this directory:  uv run demo.py
"""
import kitebase
import kitebase.plugins
import kitebase.utils
import kitebase.source


def setup(generate: bool = True):
    """Load plugins, compute schema, register behaviors, (re)generate model.py."""
    plugins = kitebase.plugins.PluginsManager()
    plugins.load_config("config.yaml")
    kitebase.utils.register_standard_handlers(plugins)
    plugins.load_plugins()

    app = kitebase.utils.get_app()
    app.calc_db(plugins)

    # Commons Archivable query behavior — injected, core stays agnostic (GL-19).
    from common.model import Archivable  # type: ignore
    app.add_query_behavior(Archivable)

    if generate:
        model_file = "model.py"
        if plugins.should_regenerate(model_file):
            print("Generating model.py ...")
            kitebase.source.Generator(app).generate(filename=model_file)
        else:
            print("model.py up to date.")

    return app, plugins


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
            ))

        # The role codes belong to the application: the Customers and Suppliers
        # views filter on ",C," and ",S," and stamp them on what is added there.
        if not session.query(model.PartnerRole).first():
            session.add_all([
                model.PartnerRole(id="C", label="Customer", sequence=10),
                model.PartnerRole(id="S", label="Supplier", sequence=20),
            ])

        if not session.query(model.Partner).first():
            session.add_all([
                model.Partner(kind="person", name="Smith, John", roles=",C,",
                              city="Bristol", email="john@example.com"),
                model.Partner(kind="organization", name="Riverside Hardware Ltd",
                              roles=",S,", city="Leeds"),
                # Both at once — the case that makes one table worth having.
                model.Partner(kind="organization", name="Northwind Trading",
                              roles=",C,S,", city="Hull"),
                # No role yet: reachable only from the unfiltered list, which is
                # where a subject is promoted to customer or supplier.
                model.Partner(kind="person", name="Doe, Jane", city="York"),
            ])

        session.commit()


def main():
    app, plugins = setup()

    import model  # type: ignore  # generated
    app.initialize_db(plugins.config["db_engine"], model)
    plugins.load_all_locales()
    seed(app, model)

    print(f"Plugins loaded: {', '.join(plugins.sorted)}")
    print(f"Tables: {', '.join(sorted(app.tables.keys()))}")

    with app.get_session() as session:
        for user in session.query(model.User).all():
            print(f"User {user.id}: {user.username} <{user.email}> admin={user.is_admin}")
        print(f"Config rows: {session.query(model.Config).count()}")

    print("commons demo smoke OK")


if __name__ == "__main__":
    main()
