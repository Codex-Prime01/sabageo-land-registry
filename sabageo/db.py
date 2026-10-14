import psycopg

from sabageo import config


def connect():
    """Open a database connection. Reads config.DB each time, so tests can point it elsewhere."""
    return psycopg.connect(config.DB)
