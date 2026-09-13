"""Create the database cache table used by the security counters.

Security review H2/H4. The per-IP lead throttle and the admin login
lockout both need a counter that is shared between worker processes and
survives a restart, which LocMemCache is not. `CACHES["throttle"]` in
settings points at a DatabaseCache stored here.

This runs `createcachetable` rather than declaring a model, because the
table is Django's own cache schema and is not part of the §6 data model -
no model, no ORM access, nothing in Admin. Doing it as a migration rather
than a documented deploy step means a fresh environment cannot come up
with a throttle that silently fails open.

`createcachetable` is idempotent: it checks for the table first and does
nothing if it already exists, so re-running this migration is safe.
"""

from django.core.management import call_command
from django.db import migrations

TABLE_NAME = "core_throttle_cache"


def create_cache_table(apps, schema_editor):
    call_command(
        "createcachetable",
        TABLE_NAME,
        database=schema_editor.connection.alias,
        verbosity=0,
    )


def drop_cache_table(apps, schema_editor):
    # Only counters live here, so dropping it loses nothing but the
    # in-flight rate-limit state.
    # TABLE_NAME is a module constant, never user input.
    schema_editor.execute(f'DROP TABLE IF EXISTS "{TABLE_NAME}"')


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
