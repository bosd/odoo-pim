"""Installation hooks for attribute_set_jsonb.

The post_init_hook handles migration of attribute_set's serialized field
columns from TEXT to JSONB and creates GIN indexes for filtering.

Each conversion runs in its own savepoint: a failure leaves the column as
TEXT and the rest of the module installation untouched. Views and
materialized views reading the column would make PostgreSQL refuse the type
change; they are dropped and recreated from their own definition around the
conversion.
"""

import logging

from psycopg2 import Error as Psycopg2Error
from psycopg2 import sql

_logger = logging.getLogger(__name__)


def _dependent_views(cr, table_name, column_name):
    """Return the views depending (directly or not) on a column.

    Each item is ``(schema, name, relkind, definition, index_definitions)``,
    ordered so that recreating them in that order respects their own
    dependencies (dropping goes the other way round).
    """
    cr.execute(
        """
        WITH RECURSIVE deps(oid, depth) AS (
            SELECT DISTINCT r.ev_class, 1
              FROM pg_depend d
              JOIN pg_rewrite r ON r.oid = d.objid
              JOIN pg_attribute a
                ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid
             WHERE d.classid = 'pg_rewrite'::regclass
               AND d.refobjid = %s::regclass
               AND a.attname = %s
               AND r.ev_class <> d.refobjid
            UNION
            SELECT r.ev_class, deps.depth + 1
              FROM deps
              JOIN pg_depend d ON d.refobjid = deps.oid
              JOIN pg_rewrite r ON r.oid = d.objid
             WHERE d.classid = 'pg_rewrite'::regclass
               AND r.ev_class <> deps.oid
        )
        SELECT n.nspname, c.relname, c.relkind,
               pg_get_viewdef(c.oid),
               ARRAY(SELECT pg_get_indexdef(i.indexrelid)
                       FROM pg_index i WHERE i.indrelid = c.oid)
          FROM (SELECT oid, max(depth) AS depth FROM deps GROUP BY oid) v
          JOIN pg_class c ON c.oid = v.oid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         ORDER BY v.depth, c.relname
        """,
        (table_name, column_name),
    )
    return cr.fetchall()


def _view_kind(relkind):
    return sql.SQL("MATERIALIZED VIEW" if relkind == "m" else "VIEW")


def _convert_column(cr, table_name, column_name):
    """Convert one column to JSONB, recreating the views reading it."""
    views = _dependent_views(cr, table_name, column_name)
    for schema, name, relkind, _definition, _indexes in reversed(views):
        _logger.info(
            "Dropping %s %s.%s (depends on %s.%s), recreated after conversion",
            "materialized view" if relkind == "m" else "view",
            schema,
            name,
            table_name,
            column_name,
        )
        # Identifiers only, read from the catalog.
        cr.execute(  # pylint: disable=sql-injection
            sql.SQL("DROP {kind} {view}").format(
                kind=_view_kind(relkind),
                view=sql.Identifier(schema, name),
            )
        )
    cr.execute(
        sql.SQL(
            """
            ALTER TABLE {table}
            ALTER COLUMN {column}
            TYPE jsonb
            USING CASE
                WHEN {column} IS NULL THEN NULL
                WHEN {column} = '' THEN '{{}}'::jsonb
                ELSE {column}::jsonb
            END
            """
        ).format(
            table=sql.Identifier(table_name),
            column=sql.Identifier(column_name),
        )
    )
    for schema, name, relkind, definition, indexes in views:
        # The definition is PostgreSQL's own pg_get_viewdef() output.
        cr.execute(  # pylint: disable=sql-injection
            sql.SQL("CREATE {kind} {view} AS {definition}").format(
                kind=_view_kind(relkind),
                view=sql.Identifier(schema, name),
                definition=sql.SQL(definition.rstrip().rstrip(";")),
            )
        )
        for index_definition in indexes:
            cr.execute(index_definition)


def post_init_hook(env):
    """Post-installation hook to migrate attribute_set columns to JSONB.

    This hook specifically targets the x_custom_json_attrs columns used by
    attribute_set for serialized attribute storage.
    """
    cr = env.cr

    _logger.info("attribute_set_jsonb: Starting post-install migration...")

    # Find all x_custom_json_attrs columns (attribute_set's serialization field)
    cr.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE column_name = 'x_custom_json_attrs'
          AND table_schema = current_schema()
        ORDER BY table_name
        """
    )
    columns_to_migrate = cr.fetchall()

    migrated_count = 0
    index_count = 0

    for table_name, column_name, data_type in columns_to_migrate:
        # Migrate TEXT to JSONB if needed
        if data_type == "text":
            _logger.info(
                "Migrating %s.%s from TEXT to JSONB...", table_name, column_name
            )
            try:
                with cr.savepoint(flush=False):
                    _convert_column(cr, table_name, column_name)
                migrated_count += 1
                _logger.info(
                    "Successfully migrated %s.%s to JSONB", table_name, column_name
                )
            except Psycopg2Error as e:
                # The savepoint is rolled back: the column stays TEXT and the
                # views reading it are left as they were.
                _logger.warning(
                    "Could not migrate %s.%s to JSONB: %s", table_name, column_name, e
                )
                continue

        # Create GIN index if not exists
        index_name = f"idx_{table_name}_{column_name}_gin"
        cr.execute(
            """
            SELECT 1 FROM pg_indexes
            WHERE tablename = %s AND indexname = %s
            """,
            (table_name, index_name),
        )
        if not cr.fetchone():
            _logger.info("Creating GIN index on %s.%s...", table_name, column_name)
            try:
                create_index_query = sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS {index}
                    ON {table} USING GIN ({column})
                    """
                ).format(
                    index=sql.Identifier(index_name),
                    table=sql.Identifier(table_name),
                    column=sql.Identifier(column_name),
                )
                with cr.savepoint(flush=False):
                    cr.execute(create_index_query)
                index_count += 1
                _logger.info("Created GIN index %s", index_name)
            except Psycopg2Error as e:
                _logger.warning(
                    "Could not create GIN index on %s.%s: %s",
                    table_name,
                    column_name,
                    e,
                )

    _logger.info(
        "attribute_set_jsonb: Migration complete. "
        "Migrated %d columns, created %d GIN indexes.",
        migrated_count,
        index_count,
    )
