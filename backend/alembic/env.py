from alembic import context

from app.db import Base, engine

target_metadata = Base.metadata
if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # SQLite batch migrations reconstruct parent tables. Disable cascades on
            # this migration connection and validate the complete foreign-key graph.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            try:
                if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                    raise RuntimeError("SQLite migration left invalid foreign-key references")
            finally:
                connection.commit()
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
