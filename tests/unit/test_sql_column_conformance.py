"""
Static SQL ⇄ schema conformance tests (no database required).

WHY THIS FILE EXISTS
--------------------
Two production bugs shipped because a query named columns that do not exist on
the table it queried, and nothing in the repo compared the two:

  * `modules/payroll_logic.get_payroll_summary()` read
    `wbom_salary_records.amount` / `.status` / `.salary_month`. Production
    stores `net_salary` / `payment_status` and splits the period across
    `month` + `year` (migration 029, a pg_dump of the live database). Every
    call raised `UndefinedColumnError`; the caller swallowed it, so every
    employee silently reported as "under review".

  * `modules/fazle_admin_commands.nl_payments` filtered on
    `t.payment_mobile` / `e.employee_mobile` for
    `fazle_cash_transactions t` / `fazle_employees e`. The real columns are
    `t.payout_phone` / `e.primary_phone`. It crashed on every query that
    contained a phone number.

`tests/conftest.py`'s fixture schema is itself wrong for these tables (it uses
the same non-production `amount`/`status`/`salary_month` names), so DB-backed
tests could never have caught either bug — they validate the code against a
guess, not against the migrations. See
`audits/NAMING_MISMATCH_AUDIT_2026-10-24.md`.

WHAT THIS FILE DOES INSTEAD
---------------------------
Builds the authoritative schema by replaying every SQL file in the repo (all
four migration directories), then walks the AST of the production modules and
resolves every column reference in their SQL string literals against it. No
connection, no fixtures, no imports of the modules under test — so it cannot
be fooled by a stale fixture and it runs anywhere.

Run:  pytest tests/unit/test_sql_column_conformance.py -v
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]

# Every directory that contributes schema, in the order a fresh database
# would see them. `db/migrate.py` only walks `db/migrations/` — the other
# three are legacy/historical but still authoritative for what production
# looks like (see db/MIGRATION_INVENTORY.md).
MIGRATION_DIRS = (
    "modules/fazle_payroll_engine/migrations",
    "migrations",
    "db/migrations",
)

# Standalone bootstrap scripts that are not part of any runner but do create
# tables (db/new_tables.sql is still referenced by docs and by migration 003).
EXTRA_SQL = ("db/new_tables.sql",)

VIEW_PREFIX = "ai_read_"


# ─────────────────────────────────────────────────────────────────────────────
# 1. A tiny SQL DDL parser — enough to reconstruct table → columns.
# ─────────────────────────────────────────────────────────────────────────────


def _strip_sql_comments(sql: str) -> str:
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            if j == -1:
                break
            i = j + 1
            out.append("\n")
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
            continue
        if c in "'\"":
            q, j = c, i + 1
            while j < n:
                if sql[j] == q:
                    if j + 1 < n and sql[j + 1] == q:
                        j += 2
                        continue
                    break
                if sql[j] == "\\":
                    j += 2
                    continue
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts, buf, depth, i, n = [], [], 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            q, j = c, i + 1
            while j < n:
                if text[j] == q:
                    if j + 1 < n and text[j + 1] == q:
                        j += 2
                        continue
                    break
                if text[j] == "\\":
                    j += 2
                    continue
                j += 1
            buf.append(text[i : j + 1])
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts]


def _split_statements(sql: str) -> list[str]:
    stmts, buf, depth, i, n = [], [], 0, 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"":
            q, j = c, i + 1
            while j < n:
                if sql[j] == q:
                    if j + 1 < n and sql[j + 1] == q:
                        j += 2
                        continue
                    break
                if sql[j] == "\\":
                    j += 2
                    continue
                j += 1
            buf.append(sql[i : j + 1])
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == ";" and depth <= 0:
            stmts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    if "".join(buf).strip():
        stmts.append("".join(buf))
    return [s.strip() for s in stmts if s.strip()]


_CREATE_RE = re.compile(
    r"^\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+|UNLOGGED\s+)?TABLE\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([\w.]+)\s*\(",
    re.I,
)
_ALTER_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?([\w.]+)\s+(.*)$", re.I | re.S
)
_DROP_RE = re.compile(r"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\w.]+)", re.I)
_CONSTRAINT_RE = re.compile(
    r"^\s*(CONSTRAINT|PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK|EXCLUDE|LIKE)\b", re.I
)


def _norm_ident(tok: str) -> str:
    tok = tok.strip()
    if tok.startswith('"'):
        return tok.strip('"')
    return tok.lower().split(".")[-1].strip('"')


def _parse_column_defs(body: str) -> list[str]:
    cols = []
    for part in _split_top_level(body):
        if not part or _CONSTRAINT_RE.match(part):
            continue
        m = re.match(r'^"([^"]+)"|^\'?([A-Za-z_][\w]*)\'?', part.strip())
        if not m:
            continue
        cols.append((m.group(1) or m.group(2)).lower())
    return cols


def _apply_statement(schema: dict[str, list[str]], stmt: str) -> None:
    """Fold one DDL statement into `schema`. Non-DDL statements are ignored."""
    m = _CREATE_RE.match(stmt)
    if m:
        table = _norm_ident(m.group(1))
        body = stmt[m.end() :]
        body = body[: body.rfind(")")]
        schema.setdefault(table, [])
        for col in _parse_column_defs(body):
            if col not in schema[table]:
                schema[table].append(col)
        return

    m = _ALTER_RE.match(stmt)
    if m:
        table = _norm_ident(m.group(1))
        for action in _split_top_level(m.group(2)):
            a = action.strip()
            if not a:
                continue
            rm = re.match(r"^RENAME\s+TO\s+([\w.]+)\s*$", a, re.I)
            if rm:
                new_name = _norm_ident(rm.group(1))
                if table in schema and new_name not in schema:
                    schema[new_name] = schema.pop(table)
                continue
            am = re.match(
                r"^ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([\w\"]+)\s",
                a,
                re.I,
            )
            if am and table in schema:
                col = am.group(1).strip('"').lower()
                if col not in schema[table]:
                    schema[table].append(col)
                continue
            am = re.match(
                r"^DROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?([\w\"]+)\s*$", a, re.I
            )
            if am and table in schema:
                col = am.group(1).strip('"').lower()
                if col in schema[table]:
                    schema[table].remove(col)
                continue
            am = re.match(
                r"^RENAME\s+(?:COLUMN\s+)?([\w\"]+)\s+TO\s+([\w\"]+)\s*$", a, re.I
            )
            if am and table in schema:
                old, new_col = (
                    am.group(1).strip('"').lower(),
                    am.group(2).strip('"').lower(),
                )
                if old in schema[table]:
                    schema[table][schema[table].index(old)] = new_col

        return

    m = _DROP_RE.match(stmt)
    if m:
        schema.pop(_norm_ident(m.group(1)), None)


def _apply(path: Path, schema: dict[str, list[str]]) -> None:
    sql = _strip_sql_comments(path.read_text(encoding="utf-8", errors="replace"))
    for stmt in _split_statements(sql):
        _apply_statement(schema, stmt)


def build_schema() -> dict[str, list[str]]:
    """Replay every migration twice: once to create tables, once to pick up
    ALTERs whose base table is defined in a later-numbered directory."""
    files: list[Path] = []
    for rel in MIGRATION_DIRS:
        files += sorted((ROOT / rel).glob("*.sql"), key=lambda p: p.name)
    files += [ROOT / rel for rel in EXTRA_SQL if (ROOT / rel).exists()]
    schema: dict[str, list[str]] = {}
    for path in files:
        _apply(path, schema)
    for path in files:  # second pass is idempotent
        _apply(path, schema)
    return schema


SCHEMA = build_schema()
ALL_COLUMNS = {c for cols in SCHEMA.values() for c in cols}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Extract SQL string literals from a module without importing it.
# ─────────────────────────────────────────────────────────────────────────────

# Also matches bare boolean fragments like `"AND (t.payout_phone = $3 ...)"`,
# which is exactly how nl_payments builds its phone filters — a fragment with
# no SELECT/FROM of its own. Missing those is how the original bug slipped
# through every existing test.
_SQL_MARKER = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|FROM|JOIN|WHERE)\b"
    r"|(?:^|\s)(?:AND|OR)\s*\(",
    re.I,
)


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _literal(node: ast.AST) -> str | None:
    """Flatten a string constant or an f-string into a checkable SQL-ish blob."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # f-string: keep the literal parts
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
            else:
                out.append(" {} ")
        return "".join(out)
    return None


def sql_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    docs = _docstring_ids(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if id(node) in docs:
            continue
        text = _literal(node)
        if text and _SQL_MARKER.search(text):
            found.append((getattr(node, "lineno", 0), text))
    return found


# ─────────────────────────────────────────────────────────────────────────────
# 3. Column-reference extraction.
# ─────────────────────────────────────────────────────────────────────────────

_SQL_KEYWORDS = {
    "select", "from", "where", "group", "by", "order", "having", "limit", "offset",
    "on", "join", "left", "right", "inner", "outer", "full", "cross", "as", "and",
    "or", "not", "null", "is", "in", "exists", "between", "like", "ilike", "case",
    "when", "then", "else", "end", "distinct", "asc", "desc", "union", "all",
    "returning", "conflict", "do", "nothing", "using", "interval", "date",
    "timestamp", "timestamptz", "text", "integer", "bigint", "numeric", "jsonb",
    "any", "some", "true", "false", "now", "current_date", "current_timestamp",
    "extract", "epoch", "count", "sum", "avg", "min", "max", "coalesce",
    "greatest", "least", "lower", "upper", "length", "trim", "substring",
    "replace", "split_part", "row_number", "rank", "lag", "lead", "abs", "round",
    "ceil", "floor", "nullif", "cast", "array_agg", "string_agg", "jsonb_agg",
    "jsonb_build_object", "jsonb_set", "to_char", "to_date", "date_trunc", "over",
    "partition", "filter", "within", "lateral", "values", "set", "into", "delete",
    "update", "insert", "table", "if", "nulls", "first", "last", "similarity",
    "array", "to_tsvector", "plainto_tsquery", "unnest", "string_to_array",
}

_STRIP_LITERALS = re.compile(r"'(?:[^'\\]|\\.)*'")
_QUALIFIED = re.compile(r"(?<![\w.\"])([A-Za-z_]\w{0,30})\.([A-Za-z_]\w*)\b")
_BARE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\b(?!\s*\()")
_ALIAS_DECL = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)"
    r"(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?",
    re.I,
)
_ALIAS_STOP = {
    "set", "where", "on", "using", "group", "order", "limit", "union", "left",
    "right", "inner", "join", "full", "cross", "values", "returning", "do",
    "nothing", "and", "or", "not", "having", "offset", "when", "then", "else",
    "end", "as", "select", "from", "by", "asc", "desc", "distinct", "case",
    "ilike", "like", "in", "is", "null", "exists", "between", "conflict",
}


def file_alias_map(path: Path) -> dict[str, set[str]]:
    """alias → set of tables it can mean, across every SQL literal in the file.

    A single file may reuse `e` for different tables in different statements,
    so we keep the union and only judge a reference when the alias is
    unambiguous — that keeps the check sound (no false positives).
    """
    aliases: dict[str, set[str]] = {}
    for _lineno, text in sql_literals(path):
        sql = _STRIP_LITERALS.sub(" '' ", text)
        for m in _ALIAS_DECL.finditer(sql):
            table = m.group(1).lower()
            alias = m.group(2)
            if alias and alias.lower() not in _ALIAS_STOP:
                aliases.setdefault(alias.lower(), set()).add(table)
            elif not alias and table in SCHEMA:
                aliases.setdefault(table, set()).add(table)
    return aliases


def qualified_refs(path: Path) -> list[tuple[int, str, str, str]]:
    """(line, table, column, snippet) for every unambiguous `alias.column`."""
    aliases = file_alias_map(path)
    out: list[tuple[int, str, str, str]] = []
    seen: set[tuple[int, str, str]] = set()
    for lineno, text in sql_literals(path):
        sql = _STRIP_LITERALS.sub(" '' ", text)
        for m in _QUALIFIED.finditer(sql):
            alias, col = m.group(1).lower(), m.group(2).lower()
            tables = {t for t in aliases.get(alias, ()) if t in SCHEMA}
            if len(tables) != 1:
                continue  # ambiguous alias — stay silent rather than guess
            table = next(iter(tables))
            if col in SCHEMA.get(table, ()):
                continue
            key = (lineno, table, col)
            if key in seen:
                continue
            seen.add(key)
            out.append((lineno, table, col, " ".join(sql.split())[:160]))
    return out


_INSERT_RE = re.compile(r"INSERT\s+INTO\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", re.I | re.S)
_UPDATE_RE = re.compile(
    r"UPDATE\s+(?:ONLY\s+)?([A-Za-z_]\w*)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?\s+SET\s+"
    r"(.*?)(?=\bWHERE\b|\bRETURNING\b|$)",
    re.I | re.S,
)


def dml_column_refs(path: Path) -> list[tuple[int, str, str, str]]:
    """(line, table, column, kind) for INSERT column lists and UPDATE SET clauses.

    These name their table explicitly, so unlike `alias.column` they need no
    alias resolution — which makes this the highest-precision half of the check.
    """
    out: list[tuple[int, str, str, str]] = []
    seen: set[tuple[int, str, str]] = set()

    def add(lineno: int, table: str, col: str, kind: str) -> None:
        col = col.strip().lower()
        if not col or col.isdigit() or col.startswith("{"):
            return  # f-string placeholder, not a column
        if col in SCHEMA.get(table, ()):
            return
        key = (lineno, table, col)
        if key in seen:
            return
        seen.add(key)
        out.append((lineno, table, col, kind))

    for lineno, text in sql_literals(path):
        sql = _STRIP_LITERALS.sub(" '' ", text)
        for m in _INSERT_RE.finditer(sql):
            table = m.group(1).lower()
            if table not in SCHEMA:
                continue
            for col in m.group(2).split(","):
                add(lineno, table, col, "INSERT")
        for m in _UPDATE_RE.finditer(sql):
            table = m.group(1).lower()
            alias = (m.group(2) or "").lower()
            if alias in {"set", "as"}:
                alias = ""
            if table not in SCHEMA:
                continue
            for part in re.split(r",(?![^()]*\))", m.group(3)):
                cm = re.match(r"^\s*([A-Za-z_]\w*)\s*=", part)
                if cm:
                    add(lineno, table, cm.group(1), "UPDATE SET")
    return out


def select_list(sql: str) -> list[str]:
    """Column names in a single-table SELECT list, with `AS` aliases removed."""
    m = re.search(r"\bSELECT\b(.*?)\bFROM\b", sql, re.I | re.S)
    if not m:
        return []
    cols = []
    for item in _split_top_level(_STRIP_LITERALS.sub(" '' ", m.group(1))):
        item = re.sub(r"\s+AS\s+[A-Za-z_]\w*\s*$", "", item.strip(), flags=re.I)
        item = re.sub(r"\s+[A-Za-z_]\w*\s*$", "", item.strip())
        mm = _BARE.search(item)
        if mm:
            cols.append(mm.group(1).lower())
    return [c for c in cols if c and c not in _SQL_KEYWORDS]


def where_columns(sql: str) -> list[str]:
    m = re.search(r"\bWHERE\b(.*?)(?:\bORDER\s+BY\b|\bLIMIT\b|$)", sql, re.I | re.S)
    if not m:
        return []
    clause = _STRIP_LITERALS.sub(" '' ", m.group(1))
    clause = re.sub(r"\$\d+", " ", clause)
    return [
        w.lower()
        for w in _BARE.findall(clause)
        if w.lower() not in _SQL_KEYWORDS and len(w) > 2
    ]


def sql_for(path: Path, func_name: str, must_contain: str) -> tuple[int, str]:
    """Find the SQL literal inside `func_name` that mentions `must_contain`."""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != func_name:
                continue
            for sub in ast.walk(node):
                text = _literal(sub)
                if text and must_contain in text:
                    return getattr(sub, "lineno", 0), text
    raise AssertionError(
        f"No SQL literal containing {must_contain!r} found in {func_name}()"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Regression tests — bug 1: wbom_salary_records
# ─────────────────────────────────────────────────────────────────────────────

PAYROLL_LOGIC = ROOT / "modules/payroll_logic/__init__.py"


class TestWbomSalaryRecordsColumnsExist:
    """`get_payroll_summary()` must use production's wbom_salary_records names.

    Production (migration 029, captured by pg_dump from the live database)
    defines: salary_id, employee_id, month, year, basic_salary, total_programs,
    program_allowance, other_allowance, total_advances, total_deductions,
    net_salary, payment_date, payment_status, remarks — with
    UNIQUE (employee_id, month, year). There is no `salary_month`, no `amount`
    and no `status`.
    """

    def test_selected_columns_all_exist(self):
        _lineno, sql = sql_for(
            PAYROLL_LOGIC, "get_payroll_summary", "wbom_salary_records"
        )
        bad = [c for c in select_list(sql) if c not in SCHEMA["wbom_salary_records"]]
        assert not bad, (
            f"get_payroll_summary() selects non-existent wbom_salary_records "
            f"columns {bad}. Production columns: {SCHEMA['wbom_salary_records']}"
        )

    def test_filter_columns_all_exist(self):
        _lineno, sql = sql_for(
            PAYROLL_LOGIC, "get_payroll_summary", "wbom_salary_records"
        )
        # Deliberately NOT restricted to names that exist elsewhere: the old
        # query's `salary_month` exists on no table in any migration, so a
        # "only flag names we recognise" rule would have let it through.
        bad = [c for c in where_columns(sql) if c not in SCHEMA["wbom_salary_records"]]
        assert not bad, (
            f"get_payroll_summary() filters on non-existent wbom_salary_records "
            f"columns {bad}. Production columns: {SCHEMA['wbom_salary_records']}"
        )

    def test_period_is_month_plus_year_not_salary_month(self):
        """The old query sent a 'YYYY-MM' string against a column that does not
        exist. Production stores the period as two integers."""
        _lineno, sql = sql_for(
            PAYROLL_LOGIC, "get_payroll_summary", "wbom_salary_records"
        )
        cols = set(where_columns(sql))
        assert "salary_month" not in cols, (
            "salary_month does not exist on wbom_salary_records"
        )
        assert {"month", "year"} <= cols, (
            "the period must be matched on the UNIQUE (employee_id, month, year) "
            f"key; WHERE currently references {sorted(cols)}"
        )

    def test_two_args_bound_for_the_two_integer_columns(self):
        """Regression guard on the binding order: month then year."""
        src = PAYROLL_LOGIC.read_text(encoding="utf-8")
        assert "month_start.month, month_start.year" in src, (
            "expected the month/year bind to come from month_start"
        )

    def test_payment_status_compared_case_insensitively(self):
        """Production's DEFAULT is 'Pending' (capitalised); a lower-case-only
        comparison would never match and the note would never be emitted."""
        src = PAYROLL_LOGIC.read_text(encoding="utf-8")
        assert '.strip().lower()' in src


# ─────────────────────────────────────────────────────────────────────────────
# 5. Regression tests — bug 2: nl_payments phone filters
# ─────────────────────────────────────────────────────────────────────────────

NL_PAYMENTS = ROOT / "modules/fazle_admin_commands/nl_payments.py"


class TestNlPaymentsPhoneFilterColumnsExist:
    """Both phone filters join `fazle_cash_transactions t` to `fazle_employees e`.

    The only phone columns on those tables are `t.payout_phone`,
    `t.employee_phone`, `t.employee_id_phone`, `e.primary_phone` and
    `e.employee_id_phone`. `payment_mobile` exists only on the legacy
    `fazle_cash_transactions_archive`; `employee_mobile` only on the legacy
    `fazle_employees_legacy`.
    """

    def test_phone_filters_use_real_columns(self):
        """Check the SQL literals themselves, not the raw source — a comment
        naming the old columns must not be able to satisfy (or trip) this."""
        offenders = []
        for lineno, text in sql_literals(NL_PAYMENTS):
            sql = _STRIP_LITERALS.sub(" '' ", text)
            for m in _QUALIFIED.finditer(sql):
                alias, col = m.group(1).lower(), m.group(2).lower()
                if (alias, col) in {
                    ("t", "payment_mobile"),
                    ("e", "employee_mobile"),
                }:
                    offenders.append(f"  {NL_PAYMENTS.name}:{lineno}: {alias}.{col}")
        assert not offenders, (
            "fazle_cash_transactions has no `payment_mobile` (it is "
            "`payout_phone`) and fazle_employees has no `employee_mobile` "
            "(it is `primary_phone`):\n" + "\n".join(offenders)
        )

    def test_where_phone_fragment_matches_schema(self):
        """The `where_phone` / `where_clause` fragments are built as separate
        string literals, so alias resolution has to happen per-file. Prove the
        check actually reaches them (they must name the real columns) *and*
        that nothing else in there is unknown."""
        used: set[tuple[str, str]] = set()
        for _lineno, text in sql_literals(NL_PAYMENTS):
            sql = _STRIP_LITERALS.sub(" '' ", text)
            for m in _QUALIFIED.finditer(sql):
                used.add((m.group(1).lower(), m.group(2).lower()))

        assert ("t", "payout_phone") in used, (
            "no `t.payout_phone` filter found — the phone branch has been "
            "removed or renamed, so this regression test no longer covers it"
        )
        assert ("e", "primary_phone") in used, (
            "no `e.primary_phone` filter found — the phone branch has been "
            "removed or renamed, so this regression test no longer covers it"
        )

        allowed = {
            ("fazle_cash_transactions", "payout_phone"),
            ("fazle_employees", "primary_phone"),
            ("fazle_employees", "employee_id_phone"),
            ("fazle_employees", "wbom_employee_id"),
        }
        bad = sorted({(t, c) for _ln, t, c, _s in qualified_refs(NL_PAYMENTS)} - allowed)
        assert not bad, f"nl_payments references non-existent columns: {bad}"

    def test_no_qualified_ref_in_nl_payments_is_unknown(self):
        refs = qualified_refs(NL_PAYMENTS)
        assert not refs, (
            "nl_payments references columns that no migration defines:\n"
            + "\n".join(
                f"  {NL_PAYMENTS.name}:{ln}: {t}.{c}\n      {s}"
                for ln, t, c, s in refs
            )
        )

    def test_employee_totals_routes_legacy_id_through_wbom_employee_id(self):
        """`emp_row` is resolved from fazle_employees_legacy, whose employee_id
        is a DIFFERENT key space from fazle_cash_transactions.employee_id
        (that FKs fazle_employees.id). Filtering on t.employee_id = <legacy id>
        matched an unrelated employee with the same number."""
        src = NL_PAYMENTS.read_text(encoding="utf-8")
        assert 'where_clause = "AND e.wbom_employee_id = $1"' in src, (
            "intent_employee_totals() must bridge the WBOM id through "
            "fazle_employees.wbom_employee_id, not compare it to t.employee_id"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Regression tests — bug 3: fazle_knowledge_base columns
# ─────────────────────────────────────────────────────────────────────────────

_VIEW_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.]+)\s+AS\s+(.*?)(?=;|$)",
    re.I | re.S,
)


def fresh_build_violations(files: list[Path]) -> list[tuple[str, str, str, str]]:
    """Replay `files` against an EMPTY schema, checking statements as they come.

    Unlike the checks above, which compare against the FINAL schema, this one
    is order-sensitive: a column that exists by the end of the chain but is
    used before anything creates it is still a broken build. That is exactly
    the knowledge_base bug — migration 012's view and migration 021's INSERTs
    needed `subcategory` / `value` / `language` long before any migration
    created them.
    """
    schema: dict[str, list[str]] = {}
    found: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def note(table: str, col: str, kind: str, path: Path) -> None:
        key = (path.name, table, col)
        if key in seen:
            return
        seen.add(key)
        found.append((path.name, table, col, kind))

    for path in files:
        sql = _strip_sql_comments(path.read_text(encoding="utf-8", errors="replace"))
        for stmt in _split_statements(sql):
            flat = _STRIP_LITERALS.sub(" '' ", stmt)
            for m in _INSERT_RE.finditer(flat):
                table = m.group(1).lower()
                if table not in schema:
                    continue
                for col in m.group(2).split(","):
                    col = col.strip().lower()
                    if not col or col.isdigit() or col.startswith("{"):
                        continue
                    if col not in schema[table]:
                        note(table, col, "INSERT", path)
            vm = _VIEW_RE.match(stmt)
            if vm:
                body = flat[vm.start(2) :]
                aliases: dict[str, str] = {}
                for am in _ALIAS_DECL.finditer(body):
                    table = am.group(1).lower()
                    alias = am.group(2)
                    if alias and alias.lower() not in _ALIAS_STOP:
                        aliases[alias.lower()] = table
                    elif not alias:
                        aliases[table] = table
                for qm in _QUALIFIED.finditer(body):
                    alias, col = qm.group(1).lower(), qm.group(2).lower()
                    table = aliases.get(alias)
                    if not table or table not in schema:
                        continue
                    if col not in schema[table]:
                        note(table, col, f"VIEW {vm.group(1)}", path)
            _apply_statement(schema, stmt)
    return found


CANONICAL_MIGRATIONS = sorted((ROOT / "db/migrations").glob("*.sql"), key=lambda p: p.name)
FULL_BUILD_ORDER = (
    sorted(
        (ROOT / "modules/fazle_payroll_engine/migrations").glob("*.sql"),
        key=lambda p: p.name,
    )
    + sorted((ROOT / "migrations").glob("*.sql"), key=lambda p: p.name)
    + [ROOT / "db/new_tables.sql"]
    + CANONICAL_MIGRATIONS
)


class TestKnowledgeBaseColumnsExist:
    """`value`, `subcategory` and `language` are live production columns that
    no migration declared until now (audit §1.4).

    `value` is documented by migration 003 itself ("DB had: key, value, tags",
    then `reply_text = value`); `subcategory` is selected by migration 012's
    `ai_read_kb_articles` view; `language` is inserted by
    scripts/seed_recruitment_kb.sql and modules/kb_upload/routes.py.
    """

    def test_three_columns_are_declared(self):
        for col in ("subcategory", "value", "language"):
            assert col in SCHEMA["fazle_knowledge_base"], (
                f"fazle_knowledge_base.{col} is used by migrations 012 / 021 and "
                "by five code sites but no migration declares it"
            )

    def test_canonical_create_table_declares_them_before_012_and_021(self):
        """Migration 002 is the canonical CREATE TABLE and runs BEFORE the
        migrations that need these columns, so a from-scratch build must get
        them from there — migration 097 alone is too late."""
        body = (ROOT / "db/migrations/002_align_tables.sql").read_text(
            encoding="utf-8"
        )
        create = body[body.index("CREATE TABLE IF NOT EXISTS fazle_knowledge_base") :]
        create = create[: create.index(");")]
        for col in ("subcategory", "value", "language"):
            assert re.search(rf"^\s*{col}\s", create, re.M), (
                f"migration 002's CREATE TABLE must declare {col}"
            )

    def test_convergence_migration_exists(self):
        path = ROOT / "db/migrations/097_knowledge_base_missing_columns.sql"
        assert path.exists(), "expected migration 097 to converge existing databases"
        text = path.read_text(encoding="utf-8")
        for col in ("subcategory", "value", "language"):
            assert f"ADD COLUMN IF NOT EXISTS {col}" in text

    def test_ai_read_kb_articles_columns_exist(self):
        """Migration 012's view — the statement that actually broke a clean
        build — must only reference columns that exist by then."""
        bad = [
            v
            for v in fresh_build_violations(CANONICAL_MIGRATIONS)
            if "ai_read_kb_articles" in v[3]
        ]
        assert not bad, f"ai_read_kb_articles references missing columns: {bad}"


class TestFreshBuildsRunEndToEnd:
    """Simulate rebuilding an empty database from this repository.

    Order-sensitive: a column created by a later migration cannot be used by an
    earlier one, so this fails where a final-schema check would pass.
    """

    def test_canonical_runner_reaches_the_end(self):
        violations = fresh_build_violations(CANONICAL_MIGRATIONS)
        assert not violations, (
            "a from-scratch `db/migrate.py` run references columns that do not "
            "exist yet at that point in the chain:\n"
            + "\n".join(f"  {f}: {t}.{c}  [{k}]" for f, t, c, k in violations[:30])
        )

    def test_full_repository_build_order_reaches_the_end(self):
        violations = fresh_build_violations(FULL_BUILD_ORDER)
        assert not violations, (
            "replaying every migration directory in order references columns "
            "that do not exist yet at that point:\n"
            + "\n".join(f"  {f}: {t}.{c}  [{k}]" for f, t, c, k in violations[:30])
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Repo-wide guard — the same class of bug, anywhere.
# ─────────────────────────────────────────────────────────────────────────────

# Known remaining mismatches, carried over from
# audits/NAMING_MISMATCH_AUDIT_2026-10-24.md (§1.3–§1.7). Entries are real
# defects; each one must be fixed and then removed from this list — never
# extended.
#
# This set is now EMPTY. Sections 1.3, 1.5, 1.6 and 1.7 were fixed on
# 2026-10-25, which means every SQL column reference in the repository
# resolves to a column that some migration actually defines.
#
# The mechanism is deliberately kept rather than deleted. An empty set keeps
# the guard strict for anything new, and the `stale` assertion below still
# does its job: if a future change reintroduces a mismatch it fails as a new
# violation, and if someone "fixes" it by adding an entry here, the entry
# starts failing as stale the moment the underlying bug goes away.
KNOWN_REMAINING = set()

# The allowlist is a baseline, not an amnesty: it is what makes the guard
# usable (a permanently-red guard cannot detect *new* violations), and the
# `stale` assertion below forces each entry to be deleted the moment the
# underlying bug is fixed.

SCAN_DIRS = ("modules", "shared", "app", "scripts")


def _iter_python_files():
    for rel in SCAN_DIRS:
        d = ROOT / rel
        if d.exists():
            yield from sorted(d.rglob("*.py"))


def test_repo_wide_sql_columns_exist():
    """Every column name in production SQL must exist on the table it targets.

    Two independent halves, both high precision:
      * INSERT column lists and UPDATE SET clauses (table named explicitly);
      * `alias.column` references where the alias is unambiguous within the file.
    """
    failures: list[str] = []
    known: set[tuple[str, str, str]] = set()

    for path in _iter_python_files():
        rel = str(path.relative_to(ROOT))
        refs = [(ln, t, c, kind) for ln, t, c, kind in dml_column_refs(path)]
        refs += [(ln, t, c, "qualified") for ln, t, c, _s in qualified_refs(path)]
        for lineno, table, col, kind in refs:
            key = (rel, table, col)
            if key in KNOWN_REMAINING:
                known.add(key)
                continue
            failures.append(f"  {rel}:{lineno}  {table}.{col}  [{kind}]")

    assert not failures, (
        "SQL references columns that no migration defines "
        f"({len(failures)} new):\n" + "\n".join(sorted(failures)[:40])
    )

    stale = sorted(KNOWN_REMAINING - known)
    if stale:
        pytest.fail(
            "KNOWN_REMAINING lists mismatches that no longer reproduce — "
            "they were fixed, so they must be removed from the list:\n  "
            + "\n  ".join(f"{f}:{t}.{c}" for f, t, c in stale)
        )


def test_schema_was_actually_built():
    """Guard against the parser silently producing an empty schema."""
    assert len(SCHEMA) > 100, f"schema build looks broken: {len(SCHEMA)} tables"
    for required in (
        "wbom_salary_records",
        "fazle_cash_transactions",
        "fazle_employees",
        "fazle_employees_legacy",
    ):
        assert required in SCHEMA, f"{required} missing from parsed schema"
    assert "net_salary" in SCHEMA["wbom_salary_records"]
    assert "month" in SCHEMA["wbom_salary_records"]
    assert "year" in SCHEMA["wbom_salary_records"]
    assert "payout_phone" in SCHEMA["fazle_cash_transactions"]
    assert "primary_phone" in SCHEMA["fazle_employees"]
    assert "wbom_employee_id" in SCHEMA["fazle_employees"]


# ─────────────────────────────────────────────────────────────────────────────
# 8. Regression tests — audit §1.3, §1.5, §1.6 and §1.7
# ─────────────────────────────────────────────────────────────────────────────

ESCORT_LIFECYCLE = ROOT / "modules/escort_lifecycle/__init__.py"
PAYMENT_INGEST = ROOT / "modules/fazle_payment_ingest/__init__.py"
FPE_CHECKPOINT = ROOT / "modules/fazle_payroll_engine/checkpoint.py"
FPE_ROUTES = ROOT / "modules/fazle_payroll_engine/routes.py"


class TestEscortLifecycleLegacyNameColumn:
    """§1.3 — `fazle_employees_legacy` keeps the name in `employee_name`.

    `full_name` is a column on a *different* table (`fazle_employees`). The
    bug was invisible because `_fuzzy_employee_lookup()` wraps the query in a
    bare `except`, so every OCR release slip silently resolved to no employee
    rather than raising.
    """

    def test_selects_employee_name(self):
        _ln, sql = sql_for(
            ESCORT_LIFECYCLE, "_fuzzy_employee_lookup", "fazle_employees_legacy"
        )
        assert "employee_name" in sql, (
            "fazle_employees_legacy stores the name in `employee_name`; "
            f"the query selected: {sql}"
        )

    def test_does_not_reference_full_name(self):
        _ln, sql = sql_for(
            ESCORT_LIFECYCLE, "_fuzzy_employee_lookup", "fazle_employees_legacy"
        )
        assert "full_name" not in sql, (
            "`full_name` is a fazle_employees column; using it on "
            "fazle_employees_legacy raises UndefinedColumnError"
        )

    def test_result_dict_key_followed_the_rename(self):
        """Renaming the column but not the dict key would break the return."""
        src = ESCORT_LIFECYCLE.read_text(encoding="utf-8")
        assert "r['employee_name']" in src
        assert "r['full_name']" not in src


class TestPaymentDraftMethodColumn:
    """§1.5 — `fazle_payment_drafts` has `payment_method`, not `method`."""

    def test_insert_uses_payment_method(self):
        # Match the statement, not the bare table name: the function's
        # docstring also mentions fazle_payment_drafts and sql_for() would
        # return that first.
        _ln, sql = sql_for(
            PAYMENT_INGEST, "_bridge_to_finalize", "INSERT INTO fazle_payment_drafts"
        )
        assert "payment_method" in sql, (
            "every other writer to fazle_payment_drafts uses `payment_method`; "
            f"this INSERT used: {sql}"
        )

    def test_insert_does_not_use_bare_method(self):
        # Match the statement, not the bare table name: the function's
        # docstring also mentions fazle_payment_drafts and sql_for() would
        # return that first.
        _ln, sql = sql_for(
            PAYMENT_INGEST, "_bridge_to_finalize", "INSERT INTO fazle_payment_drafts"
        )
        assert not re.search(r"\bmethod\b", sql), (
            "fazle_payment_drafts has no `method` column"
        )

    def test_parser_dict_key_left_alone(self):
        """`method` is also the *parser's* dict key — only SQL changes."""
        src = PAYMENT_INGEST.read_text(encoding="utf-8")
        assert 'parsed["method"]' in src


class TestSyncCheckpointColumnName:
    """§1.6 — `fpe_sync_checkpoints` has `last_sync_at`.

    `last_checked_at` is a real column, but on `social_backlog_state`; it was
    carried into the FPE checkpoint code by copy-paste. Because
    `touch_checkpoint()` runs on *every* sync pass, this raised on every pass.
    """

    def test_get_checkpoint_does_not_select_last_checked_at(self):
        _ln, sql = sql_for(FPE_CHECKPOINT, "get_checkpoint", "fpe_sync_checkpoints")
        assert "last_checked_at" not in sql
        assert "last_sync_at" in sql

    def test_touch_checkpoint_updates_last_sync_at(self):
        _ln, sql = sql_for(FPE_CHECKPOINT, "touch_checkpoint", "fpe_sync_checkpoints")
        assert "SET last_sync_at = NOW()" in sql
        assert "last_checked_at" not in sql

    def test_sync_status_endpoint_does_not_select_last_checked_at(self):
        _ln, sql = sql_for(FPE_ROUTES, "sync_status", "fpe_sync_checkpoints")
        assert "last_checked_at" not in sql

    def test_last_checked_at_is_not_a_column_of_this_table(self):
        """Documents *why* the three assertions above are correct."""
        assert "last_sync_at" in SCHEMA["fpe_sync_checkpoints"]
        assert "last_checked_at" not in SCHEMA["fpe_sync_checkpoints"]


class TestGapScanRunsSkippedNoContent:
    """§1.7 — `fpe_gap_scan_runs.skipped_no_content`.

    gap_scan.py INSERTs this column on every run, but no migration ever
    created it, so the INSERT failed and *no* scan run was ever recorded.
    Dropping the column from the INSERT would have discarded the
    `real_gaps = missing - skipped` signal, so the column was added instead.
    """

    def test_column_is_declared(self):
        assert "skipped_no_content" in SCHEMA["fpe_gap_scan_runs"], (
            "gap_scan.py INSERTs fpe_gap_scan_runs.skipped_no_content but no "
            "migration declares it"
        )

    def test_create_table_declares_it(self):
        body = (
            ROOT
            / "modules/fazle_payroll_engine/migrations/004_fpe_zero_loss.sql"
        ).read_text(encoding="utf-8")
        create = body[body.index("CREATE TABLE IF NOT EXISTS fpe_gap_scan_runs") :]
        create = create[: create.index(");")]
        assert re.search(r"^\s*skipped_no_content\s", create, re.M), (
            "migration 004's CREATE TABLE must declare skipped_no_content for "
            "from-scratch builds"
        )

    def test_convergence_migration_exists(self):
        """004 uses CREATE TABLE IF NOT EXISTS, so a database that already has
        the table would never gain the column — hence an explicit ALTER."""
        path = (
            ROOT
            / "modules/fazle_payroll_engine/migrations"
            / "015_fpe_gap_scan_skipped_no_content.sql"
        )
        assert path.exists(), "expected FPE migration 015 to converge existing DBs"
        assert "ADD COLUMN IF NOT EXISTS skipped_no_content" in path.read_text(
            encoding="utf-8"
        )
