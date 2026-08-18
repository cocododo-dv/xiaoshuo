from __future__ import annotations

from sqlalchemy import inspect


def test_every_foreign_key_column_has_a_covering_index(session) -> None:
    inspector = inspect(session.get_bind())
    uncovered: list[str] = []

    for table_name in inspector.get_table_names():
        indexes = inspector.get_indexes(table_name)
        indexed_prefixes = {
            columns[0]
            for index in indexes
            if (columns := index.get("column_names") or [])
        }
        primary_key = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
        if primary_key:
            indexed_prefixes.add(primary_key[0])
        for constraint in inspector.get_unique_constraints(table_name):
            columns = constraint.get("column_names") or []
            if columns:
                indexed_prefixes.add(columns[0])
        for foreign_key in inspector.get_foreign_keys(table_name):
            for column_name in foreign_key.get("constrained_columns") or []:
                if column_name not in indexed_prefixes:
                    uncovered.append(f"{table_name}.{column_name}")

    assert uncovered == []
