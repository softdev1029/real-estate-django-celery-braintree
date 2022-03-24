from django.core.management.base import BaseCommand
from django.db import connection


CANCEL_QUERY = """
WITH inactive_connections AS (
    SELECT
        pid,
        rank() over (partition by client_addr order by backend_start ASC) as rank
    FROM
        pg_stat_activity
    WHERE
        pid <> pg_backend_pid()
    AND
        datname = current_database()
    AND
        usename = current_user
    AND
        state in (
            'active'
            , 'idle'
            , 'idle in transaction'
            , 'idle in transaction (aborted)'
            , 'disabled'
        )
    AND
        current_timestamp - state_change > interval '%s minutes'
)
SELECT
    pg_terminate_backend(pid)
FROM
    inactive_connections;
"""


class Command(BaseCommand):
    """
    Terminates idle postgres stuck queries/connections that have persisted longer than N minutes.
    """
    def add_arguments(self, parser):
        parser.add_argument('--min', nargs='?', type=int, default=10)

    def handle(self, *args, **options):
        minutes = options["min"]
        with connection.cursor() as cursor:
            cursor.execute(
                CANCEL_QUERY,
                [minutes],
            )
