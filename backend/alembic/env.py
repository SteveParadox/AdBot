from alembic import context

from app.db import Base, engine

target_metadata = Base.metadata


def run_online(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        if connection.dialect.name != "sqlite":
            run_online(connection)
        else:
            # Batch migrations reconstruct parent tables. Suspend foreign-key
            # cascades for the rebuild, then validate before committing the DDL.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                with connection.begin():
                    connection.exec_driver_sql("BEGIN")
                    run_online(connection)
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                        raise RuntimeError("SQLite migration left invalid foreign-key references")
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
