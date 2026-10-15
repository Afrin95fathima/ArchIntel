from sqlalchemy import Engine, create_engine, event
from app.config import Settings


def build_engine(settings: Settings) -> Engine:
    sqlite = settings.database_url.startswith('sqlite:')
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, pool_pre_ping=True,
        connect_args={'check_same_thread': False, 'timeout': 30} if sqlite else {'connect_timeout': 5})
    if sqlite:
        @event.listens_for(engine, 'connect')
        def pragmas(connection, record):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine
