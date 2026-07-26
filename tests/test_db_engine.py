from __future__ import annotations

from narovva.db.engine import _split_statements


def test_leading_comment_stays_attached_to_first_statement():
    sql = """-- header comment
-- second header line

CREATE TABLE IF NOT EXISTS foo (id INT);

CREATE INDEX IF NOT EXISTS idx_foo ON foo (id);
"""
    statements = _split_statements(sql)
    assert len(statements) == 2
    assert "CREATE TABLE IF NOT EXISTS foo" in statements[0]
    assert "CREATE INDEX IF NOT EXISTS idx_foo" in statements[1]


def test_comment_only_trailing_chunk_is_dropped():
    sql = "CREATE TABLE foo (id INT);\n-- trailing comment, no statement here\n"
    statements = _split_statements(sql)
    assert statements == ["CREATE TABLE foo (id INT)"]


def test_migration_file_produces_one_statement_per_table_and_index():
    from pathlib import Path

    sql = (Path(__file__).parent.parent / "src/narovva/db/migrations/0001_init.sql").read_text()
    statements = _split_statements(sql)
    creates_post_history = [s for s in statements if "CREATE TABLE" in s and "post_history" in s]
    assert len(creates_post_history) == 1
