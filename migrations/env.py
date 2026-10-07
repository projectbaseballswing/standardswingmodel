"""Use the same environment-based engine and metadata as the API."""

from alembic import context

from api.database import Base, engine

if context.is_offline_mode():
    context.configure(url=engine.url, target_metadata=Base.metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
