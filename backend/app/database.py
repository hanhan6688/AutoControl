from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


database_url = settings.resolved_database_url


def _ensure_sqlite_parent(url: str) -> None:
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url.endswith(":memory:"):
        return
    db_path = Path(url[len(prefix):])
    db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent(database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}

engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        # ── Ensure test_case_folder table exists ──────────────────────────
        existing_tables = {
            row[0] for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "test_case_folder" not in existing_tables:
            connection.exec_driver_sql("""
                CREATE TABLE test_case_folder (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    plan_id INTEGER NOT NULL REFERENCES test_plan_project(id) ON DELETE CASCADE,
                    name VARCHAR(255) NOT NULL,
                    requirement_summary TEXT,
                    source_type VARCHAR(64),
                    source_filename VARCHAR(255),
                    sequence INTEGER DEFAULT 0,
                    total_cases INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.exec_driver_sql(
                "CREATE INDEX ix_test_case_folder_plan_id ON test_case_folder(plan_id)"
            )

        # ── Ensure imported_test_case has folder_id column ────────────────
        existing_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(imported_test_case)")
        }
        if "folder_id" not in existing_columns:
            connection.exec_driver_sql(
                "ALTER TABLE imported_test_case ADD COLUMN folder_id INTEGER REFERENCES test_case_folder(id) ON DELETE SET NULL"
            )

        # ── Auto-migrate: create default folders for existing plans ───────
        plan_rows = connection.exec_driver_sql(
            "SELECT id FROM test_plan_project WHERE id NOT IN (SELECT DISTINCT plan_id FROM test_case_folder)"
        ).fetchall()
        for (plan_id,) in plan_rows:
            # Create a "默认文档" folder for each plan that has no folders yet
            result = connection.exec_driver_sql(
                "INSERT INTO test_case_folder (plan_id, name, source_type, sequence, total_cases, created_at) "
                "VALUES (?, '默认文档', 'import_grouped', 1, 0, CURRENT_TIMESTAMP)",
                (plan_id,),
            )
            folder_id = result.lastrowid
            # Assign all folderless cases to this default folder
            connection.exec_driver_sql(
                "UPDATE imported_test_case SET folder_id = ? WHERE plan_id = ? AND folder_id IS NULL",
                (folder_id, plan_id),
            )
            # Update folder total_cases count
            count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM imported_test_case WHERE folder_id = ?",
                (folder_id,),
            ).scalar()
            connection.exec_driver_sql(
                "UPDATE test_case_folder SET total_cases = ? WHERE id = ?",
                (count, folder_id),
            )

        # ── Legacy column migrations ──────────────────────────────────────
        migrations = {
            "imported_test_case": {
                "target_app": "VARCHAR(128)",
                "test_module": "VARCHAR(128)",
            },
            "test_case_execution": {
                "autoglm_configured": "BOOLEAN NOT NULL DEFAULT 0",
                "error_category": "VARCHAR(64)",
                "trace_id": "VARCHAR(64)",
            },
            "login_account": {
                "use_for_autoglm": "BOOLEAN NOT NULL DEFAULT 1",
            },
        }

        for table_name, columns in migrations.items():
            existing_columns = {
                row[1]
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table_name})")
            }
            for column_name, definition in columns.items():
                if column_name not in existing_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                    )
        # Migrate data: copy platform_type values to test_module where applicable
        existing_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(imported_test_case)")
        }
        if "platform_type" in existing_columns and "test_module" in existing_columns:
            connection.exec_driver_sql(
                "UPDATE imported_test_case SET test_module = platform_type WHERE test_module IS NULL AND platform_type IS NOT NULL"
            )
