#!/usr/bin/env python3
"""
Issue #33: database-level audit trail for enrichment/enrichment_history writes.

remove_protected_subject_triples() (issue #26) proved that per-call-site instrumentation
misses writes made through any path that doesn't go through the instrumented call sites — nine
migration scripts plus /undo bypass the app's log_event()/take_axiom_snapshot() entirely. This
migration moves enforcement to the database itself: triggers on enrichment and
enrichment_history capture every write regardless of which code path made it, including
scripts that don't exist yet.

Purely additive: creates two new tables (write_audit_log, _write_actor) and six triggers
(INSERT/UPDATE/DELETE on each of the two audited tables). Modifies no existing table, column,
or write path.

Actor attribution (best-effort, not a guarantee — see caveat below):
_write_actor is a single-row context table that get_enrichment_db(actor=...) sets on every
connect. Triggers read it into write_audit_log.actor. A write from a connection that never
called get_enrichment_db() with an actor (raw sqlite3.connect(), as every migration script in
scripts/migrations/ uses today) leaves _write_actor at whatever the last get_enrichment_db()
call set it to — NULL if that caller passed none, or a stale actor name if it didn't and no
call happened in between. SQLite has no per-connection session-variable mechanism a trigger can
read, so this is the best available signal without a custom C extension: NULL is the honest
default and the common case for genuinely uninstrumented writes, but a script running
immediately after an app request with no intervening get_enrichment_db() call could inherit
that request's actor by coincidence. write_audit_log's primary guarantee (a write happened,
with full before/after content) is unconditional; actor attribution is secondary and
best-effort. Noted rather than solved further, per instruction.

Run once against the live database:
    python -m scripts.migrations.add_write_audit_triggers
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "enrichment.db"

AUDITED_TABLES = ["enrichment", "enrichment_history"]


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _json_object_expr(columns: list[str], ref: str) -> str:
    """Build a JSON object SQL expression for the given row alias (NEW or OLD).

    Deliberately NOT a single json_object(...) call: enrichment now has enough
    columns (65, growing) that a 2*N-arg json_object() call exceeds SQLite's
    compiled SQLITE_MAX_FUNCTION_ARG limit (hit at 65 columns / 130 args,
    "too many arguments on function json_object" -- malformed schema, breaks
    every write to the table until fixed). String concatenation via || has no
    such ceiling -- each json_quote() call takes exactly one argument.
    """
    parts = [f"'\"{c}\":' || COALESCE(json_quote({ref}.{c}), 'null')" for c in columns]
    return "('{' || " + " || ',' || ".join(parts) + " || '}')"


def _trigger_sql(table: str, op: str, columns: list[str]) -> str:
    trg_name = f"trg_{table}_audit_{op.lower()}"
    if op == "INSERT":
        row_id = "NEW.id"
        old_expr = "NULL"
        new_expr = _json_object_expr(columns, "NEW")
    elif op == "DELETE":
        row_id = "OLD.id"
        old_expr = _json_object_expr(columns, "OLD")
        new_expr = "NULL"
    else:  # UPDATE
        row_id = "NEW.id"
        old_expr = _json_object_expr(columns, "OLD")
        new_expr = _json_object_expr(columns, "NEW")

    return f"""
CREATE TRIGGER IF NOT EXISTS {trg_name}
AFTER {op} ON {table}
BEGIN
    INSERT INTO write_audit_log (table_name, row_id, op, actor, old_row, new_row)
    VALUES (
        '{table}',
        {row_id},
        '{op}',
        (SELECT actor FROM _write_actor WHERE id = 1),
        {old_expr},
        {new_expr}
    );
END;
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS write_audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name  TEXT NOT NULL,
            row_id      INTEGER NOT NULL,
            op          TEXT NOT NULL,              -- INSERT | UPDATE | DELETE
            changed_at  TEXT NOT NULL DEFAULT (datetime('now')),
            actor       TEXT,                       -- best-effort; NULL = uninstrumented or unattributed
            old_row     TEXT,                        -- JSON, NULL on INSERT
            new_row     TEXT                         -- JSON, NULL on DELETE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_write_audit_table_row ON write_audit_log(table_name, row_id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS _write_actor (
            id    INTEGER PRIMARY KEY CHECK (id = 1),
            actor TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO _write_actor (id, actor) VALUES (1, NULL)")

    created = []
    for table in AUDITED_TABLES:
        columns = _columns(conn, table)
        if not columns:
            raise RuntimeError(f"table {table!r} has no columns — refusing to generate triggers")
        for op in ("INSERT", "UPDATE", "DELETE"):
            conn.execute(_trigger_sql(table, op, columns))
            created.append(f"trg_{table}_audit_{op.lower()}")

    conn.commit()
    print(f"Created write_audit_log, _write_actor, and {len(created)} triggers:")
    for name in created:
        print(f"  {name}")


def main():
    if not DB.exists():
        print(f"ERROR: {DB} not found", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB))
    try:
        migrate(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
