"""Explicit, local-only PostgreSQL account provisioning; never imports market data."""
from __future__ import annotations

import psycopg
from psycopg import sql
from .backup import is_checkpoint_table


class PostgreSQLProvisioningRepository:
    DATABASE = "krx_research"
    OWNER = "krx_owner"
    READER = "krx_reader"
    WRITER = "krx_writer"
    MARKER = "Stock local account setup v1"
    # Session-only settings: neither statements nor bind values may expose credentials.
    QUIET_OPTIONS = (
        "-c log_statement=none -c log_min_error_statement=panic "
        "-c log_min_duration_statement=-1 -c log_min_duration_sample=-1 "
        "-c log_parameter_max_length=0 -c log_parameter_max_length_on_error=0"
    )

    def __init__(self, *, port: int = 5432, major_version: int = 16):
        if (major_version, port) not in {(16, 5432), (18, 5433)}:
            raise ValueError("지원하는 로컬 인스턴스는 PostgreSQL 16:5432 또는 18:5433입니다.")
        self.port = port
        self.major_version = major_version

    def connect(self, user: str, password: str, database: str, *, administrator=False):
        return psycopg.connect(
            host="127.0.0.1", port=self.port, dbname=database, user=user, password=password,
            connect_timeout=10, autocommit=True, application_name="stock_account_setup",
            options=self.QUIET_OPTIONS if administrator else "-c statement_timeout=15000",
        )

    def restore_status(self, read_password: str) -> dict:
        if (self.major_version, self.port) != (18, 5433):
            raise ValueError("복원 진행 조회는 PostgreSQL 18:5433 전용입니다.")
        with self.connect(self.READER, read_password, self.DATABASE) as conn:
            row = conn.execute(
                "SELECT (SELECT count(*) FROM pg_stat_progress_copy "
                "WHERE datid=(SELECT oid FROM pg_database WHERE datname=current_database())), "
                "(SELECT count(*) FROM pg_stat_progress_create_index "
                "WHERE datid=(SELECT oid FROM pg_database WHERE datname=current_database()))"
            ).fetchone()
            validation = conn.execute(
                "SELECT count(*),coalesce(max(extract(epoch FROM clock_timestamp()-query_start)),0) "
                "FROM pg_stat_activity WHERE datname=current_database() AND usename=current_user "
                "AND pid<>pg_backend_pid() AND state='active'"
            ).fetchone()
        return {"copy_operations": int(row[0]), "index_operations": int(row[1]),
                "validation_queries": int(validation[0]), "longest_query_seconds": round(float(validation[1]), 1)}

    def provision(self, admin_password: str, read_password: str, write_password: str) -> None:
        with self.connect("postgres", admin_password, "postgres", administrator=True) as admin:
            if admin.info.server_version // 10000 != self.major_version:
                raise ValueError("지정한 PostgreSQL 서버 버전과 일치하지 않습니다.")
            if self.major_version == 18 and admin.info.server_version != 180006:
                raise ValueError("복원 서버는 PostgreSQL 18.6이어야 합니다.")
            if not admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]:
                raise ValueError("설치 시 설정한 postgres 관리자 계정이 필요합니다.")
            database = admin.execute(
                "SELECT pg_get_userbyid(datdba), shobj_description(oid,'pg_database') "
                "FROM pg_database WHERE datname=%s", [self.DATABASE],
            ).fetchone()
            if database and database != (self.OWNER, self.MARKER):
                raise ValueError("기존 DB는 이 도구가 만든 DB가 아닙니다. 변경하지 않았습니다.")
            if database:
                with self.connect("postgres", admin_password, self.DATABASE, administrator=True) as target:
                    self._require_empty(target)
            # Preflight all roles before changing any of them.
            for name in (self.OWNER, self.READER, self.WRITER):
                role = admin.execute(
                    "SELECT shobj_description(oid,'pg_authid'), rolsuper, rolcreatedb, "
                    "rolcreaterole, rolreplication, rolbypassrls, "
                    "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) "
                    "FROM pg_roles WHERE rolname=%s", [name],
                ).fetchone()
                if role and (role[0] != self.MARKER or any(role[1:])):
                    raise ValueError("동명 계정이 이미 있거나 권한이 다릅니다. 변경하지 않았습니다.")
            with admin.transaction():
                for name, password in (
                    (self.OWNER, None), (self.READER, read_password), (self.WRITER, write_password),
                ):
                    role = sql.Identifier(name)
                    exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", [name]).fetchone()
                    if not exists:
                        admin.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(role))
                        admin.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(role, sql.Literal(self.MARKER)))
                    attributes = "NOLOGIN" if password is None else "LOGIN"
                    admin.execute(sql.SQL(
                        "ALTER ROLE {} " + attributes +
                        " NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(role))
                    if password is not None:
                        encrypted = admin.pgconn.encrypt_password(
                            password.encode("utf-8"), name.encode("utf-8"), b"scram-sha-256",
                        ).decode("ascii")
                        admin.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(role, sql.Literal(encrypted)))
            if not database:
                admin.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(self.DATABASE), sql.Identifier(self.OWNER),
                ))
                admin.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(self.DATABASE), sql.Literal(self.MARKER),
                ))
            with self.connect("postgres", admin_password, self.DATABASE, administrator=True) as target:
                self._require_empty(target)
                self._permissions(target)

    def _require_empty(self, conn) -> None:
        if conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','f','S'))"
        ).fetchone()[0]:
            raise ValueError("DB에 기존 자료 구조가 있습니다. 변경하지 않았습니다.")

    def _permissions(self, conn) -> None:
        db, owner, reader, writer = map(sql.Identifier, (
            self.DATABASE, self.OWNER, self.READER, self.WRITER,
        ))
        with conn.transaction():
            for statement in (
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db),
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(db, reader, writer),
                sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC"),
                sql.SQL("ALTER SCHEMA public OWNER TO {}").format(owner),
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}").format(reader, writer),
                sql.SQL("ALTER ROLE {} IN DATABASE {} SET default_transaction_read_only=on").format(reader, db),
                sql.SQL("ALTER ROLE {} IN DATABASE {} SET default_transaction_read_only=off").format(writer, db),
            ):
                conn.execute(statement)
            # These are database-local defaults for future objects, not business tables.
            for creator in (owner, sql.Identifier("postgres")):
                prefix = sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} ").format(creator)
                for grant in (
                    sql.SQL("GRANT USAGE ON SCHEMAS TO {}, {}").format(reader, writer),
                    sql.SQL("GRANT SELECT ON TABLES TO {}").format(reader),
                    sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(writer),
                    sql.SQL("GRANT USAGE, SELECT ON SEQUENCES TO {}").format(writer),
                    sql.SQL("REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"),
                ):
                    conn.execute(prefix + grant)

    def apply_restored_permissions(self, admin_password: str) -> None:
        if (self.major_version, self.port) != (18, 5433):
            raise ValueError("복원 권한 설정은 PostgreSQL 18:5433 전용입니다.")
        with self.connect("postgres", admin_password, self.DATABASE, administrator=True) as conn:
            self._permissions(conn)
            with conn.transaction():
                schemas = conn.execute(
                    "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema') "
                    "AND nspname NOT LIKE 'pg_%'"
                ).fetchall()
                for (name,) in schemas:
                    schema = sql.Identifier(name)
                    reader, writer = map(sql.Identifier, (self.READER, self.WRITER))
                    for statement in (
                        sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(schema),
                        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}, {}").format(schema, reader, writer),
                        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC").format(schema),
                        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(schema, reader),
                        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(schema, writer),
                        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(schema, writer),
                        sql.SQL("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC").format(schema),
                    ):
                        conn.execute(statement)

    def verify(self, read_password: str, write_password: str, *, require_empty: bool = True) -> None:
        for name, password, readonly in (
            (self.READER, read_password, "on"), (self.WRITER, write_password, "off"),
        ):
            with self.connect(name, password, self.DATABASE) as conn:
                identity = conn.execute(
                    "SELECT current_database(), current_user, current_setting('default_transaction_read_only'), "
                    "has_database_privilege(current_user,current_database(),'CREATE'), "
                    "has_database_privilege(current_user,current_database(),'TEMP'), "
                    "has_schema_privilege(current_user,'public','CREATE')"
                ).fetchone()
                if identity != (self.DATABASE, name, readonly, False, False, False):
                    raise ValueError("계정별 연결 또는 최소 권한 검증에 실패했습니다.")
                attributes = conn.execute(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, "
                    "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) "
                    "FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                if attributes != (False,) * 6:
                    raise ValueError("로그인 계정에 허용되지 않은 권한이 있습니다.")
                owner = conn.execute(
                    "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                    "FROM pg_roles WHERE rolname=%s", [self.OWNER],
                ).fetchone()
                if owner != (False,) * 6:
                    raise ValueError("소유자 계정 제한 검증 실패")
                grants = conn.execute(
                    "SELECT pg_get_userbyid(d.defaclrole), a.privilege_type "
                    "FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a "
                    "WHERE d.defaclobjtype='r' AND d.defaclnamespace=0 "
                    "AND a.grantee=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
                ).fetchall()
                privileges = ("SELECT",) if name == self.READER else ("SELECT", "INSERT", "UPDATE", "DELETE")
                if set(grants) != {(creator, privilege) for creator in (self.OWNER, "postgres") for privilege in privileges}:
                    raise ValueError("테이블 기본 권한 검증 실패")
                if require_empty:
                    self._require_empty(conn)
                else:
                    excessive = conn.execute(
                        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE c.relkind IN ('r','p') AND n.nspname !~ '^pg_' "
                        "AND n.nspname <> 'information_schema' AND ("
                        "NOT has_table_privilege(current_user,c.oid,'SELECT') OR "
                        "has_table_privilege(current_user,c.oid,'TRUNCATE') OR "
                        "has_schema_privilege(current_user,n.oid,'CREATE') OR "
                        "has_table_privilege(current_user,c.oid,'INSERT') <> %s OR "
                        "has_table_privilege(current_user,c.oid,'UPDATE') <> %s OR "
                        "has_table_privilege(current_user,c.oid,'DELETE') <> %s)",
                        [name == self.WRITER] * 3,
                    ).fetchone()[0]
                    if excessive:
                        raise ValueError("복원된 테이블의 계정별 최소 권한 검증 실패")
                    invalid_sequences = conn.execute(
                        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE c.relkind='S' AND n.nspname !~ '^pg_' AND ("
                        "has_sequence_privilege(current_user,c.oid,'USAGE') <> %s OR "
                        "has_sequence_privilege(current_user,c.oid,'SELECT') <> %s OR "
                        "has_sequence_privilege(current_user,c.oid,'UPDATE'))", [name == self.WRITER] * 2,
                    ).fetchone()[0]
                    if invalid_sequences:
                        raise ValueError("복원된 시퀀스의 계정별 최소 권한 검증 실패")

    def validate_restored(self, read_password: str, source: dict, *, latest_trade_date: str) -> dict:
        from krx_research.financial_backfill.models import FinancialPeriod
        from krx_research.financial_backfill.repository import FinancialRepository

        counts, checkpoints, dates = {}, {}, {}
        with self.connect(self.READER, read_password, self.DATABASE) as conn:
            conn.execute("SET statement_timeout=0")
            for key, expected in source["tables"].items():
                relation = sql.Identifier(expected["schema"], expected["table"])
                count = conn.execute(sql.SQL("SELECT count(*) FROM ONLY {}").format(relation)).fetchone()[0]
                counts[key] = int(count)
                if count != expected["rows"]:
                    raise ValueError(f"테이블 건수 불일치: {key} (backup={expected['rows']}, restored={count})")
                actual_dates = {}
                for column, maximum in expected["dates"].items():
                    actual = conn.execute(sql.SQL("SELECT max({})::text FROM ONLY {}").format(
                        sql.Identifier(column), relation,
                    )).fetchone()[0]
                    actual_dates[column] = actual
                    if actual != maximum:
                        raise ValueError(f"백업과 최신 기준일 불일치: {key}.{column}")
                    if column == "trade_date":
                        dates[key] = actual
                if is_checkpoint_table(expected["table"]):
                    statuses = {}
                    if "status" in expected["columns"]:
                        statuses = {str(value) if value is not None else r"\N": int(number)
                                    for value, number in conn.execute(sql.SQL(
                                        "SELECT status, count(*) FROM ONLY {} GROUP BY status"
                                    ).format(relation)).fetchall()}
                    if statuses != expected["statuses"]:
                        raise ValueError(f"체크포인트 상태 불일치: {key}")
                    checkpoints[key] = {"rows": int(count), "dates": actual_dates, "statuses": statuses}
            parents = conn.execute(
                "SELECT c.oid,n.nspname,c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='p' "
                "AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'"
            ).fetchall()
            for oid, schema, table in parents:
                descendants = conn.execute(
                    "WITH RECURSIVE children(oid) AS (SELECT inhrelid FROM pg_inherits WHERE inhparent=%s "
                    "UNION ALL SELECT i.inhrelid FROM pg_inherits i JOIN children c ON i.inhparent=c.oid) "
                    "SELECT n.nspname,c.relname FROM children d JOIN pg_class c ON c.oid=d.oid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace", [oid],
                ).fetchall()
                expected_count = sum(source["tables"].get(s + "." + t, {}).get("rows", 0) for s, t in descendants)
                actual = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(schema, table))).fetchone()[0]
                if actual != expected_count:
                    raise ValueError(f"파티션 부모 건수 불일치: {schema}.{table}")
                counts[schema + "." + table] = int(actual)
            if not dates or max(dates.values()) != latest_trade_date:
                raise ValueError("복원 DB의 최신 거래일이 요청된 기준일과 다릅니다.")
            if not checkpoints or not any(item["rows"] for item in checkpoints.values()):
                raise ValueError("0건이 아닌 체크포인트를 검증하지 못했습니다.")
            year, _, period_label = source["latest_financial"]
            period = FinancialPeriod.parse(period_label)
            financial = FinancialRepository(conn)
            financial_counts = financial.batch_counts()
            if not financial_counts["companies"] or not financial_counts["facts"]:
                raise ValueError("재무자료가 0건입니다.")
            latest = conn.execute("SELECT max(period_end)::text FROM financial.statement_facts").fetchone()[0]
            if latest != period.period_end(year).isoformat():
                raise ValueError("재무자료 최신 분기가 백업과 일치하지 않습니다.")
            if latest > latest_trade_date:
                raise ValueError("재무자료 최신 분기가 검증 기준일 이후입니다.")
            financial_summary = {"year": year, "period": period_label, "period_end": latest,
                                 "period_facts": financial.period_fact_count(year, period), **financial_counts}
            if not financial_summary["period_facts"]:
                raise ValueError("최신 재무 분기 자료가 0건입니다.")
        return {"table_counts": counts, "latest_trade_date": max(dates.values()),
                "trade_dates": dates, "financial": financial_summary, "checkpoints": checkpoints}
