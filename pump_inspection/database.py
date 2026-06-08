from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pump_inspection.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _migrate_inspection_shifts_table():
    """迁移 inspection_shifts 表：从 shift_id 全局唯一改为 (batch_id, shift_id) 组合唯一"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='inspection_shifts'"))
        if not result.fetchone():
            return
        
        needs_migration = False
        
        try:
            conn.execute(text("""
                INSERT INTO inspection_shifts (batch_id, shift_id, shift_date)
                VALUES (999999, 'MIGRATION_TEST_ID', '2026-01-01')
            """))
            try:
                conn.execute(text("""
                    INSERT INTO inspection_shifts (batch_id, shift_id, shift_date)
                    VALUES (999998, 'MIGRATION_TEST_ID', '2026-01-01')
                """))
                conn.rollback()
                test1_passed = True
            except Exception:
                conn.rollback()
                test1_passed = False
        except Exception:
            conn.rollback()
            test1_passed = False
        
        if not test1_passed:
            needs_migration = True
        else:
            try:
                conn.execute(text("""
                    INSERT INTO inspection_shifts (batch_id, shift_id, shift_date)
                    VALUES (999999, 'MIGRATION_TEST_ID_2', '2026-01-01')
                """))
                try:
                    conn.execute(text("""
                        INSERT INTO inspection_shifts (batch_id, shift_id, shift_date)
                        VALUES (999999, 'MIGRATION_TEST_ID_2', '2026-01-02')
                    """))
                    conn.rollback()
                    needs_migration = True
                except Exception:
                    conn.rollback()
                    needs_migration = False
            except Exception:
                conn.rollback()
                needs_migration = True
        
        if not needs_migration:
            return
        
        print("检测到巡检班次表结构需要迁移，正在升级...")
        
        conn.execute(text("ALTER TABLE inspection_shifts RENAME TO inspection_shifts_old"))
        conn.commit()
        
        from . import models
        Base.metadata.tables['inspection_shifts'].create(bind=conn)
        conn.commit()
        
        result = conn.execute(text("SELECT * FROM inspection_shifts_old"))
        rows = result.fetchall()
        result = conn.execute(text("PRAGMA table_info(inspection_shifts_old)"))
        old_columns = [col[1] if len(col) > 1 else col[0] for col in result.fetchall()]
        result = conn.execute(text("PRAGMA table_info(inspection_shifts)"))
        new_columns = [col[1] if len(col) > 1 else col[0] for col in result.fetchall()]
        common_cols = [c for c in old_columns if c in new_columns]
        
        if common_cols and rows:
            placeholders = ", ".join([f":{c}" for c in common_cols])
            cols_str = ", ".join(common_cols)
            for row in rows:
                row_dict = {col: row[i] for i, col in enumerate(old_columns)}
                try:
                    conn.execute(
                        text(f"INSERT OR IGNORE INTO inspection_shifts ({cols_str}) VALUES ({placeholders})"),
                        row_dict
                    )
                except Exception:
                    pass
            conn.commit()
        
        conn.execute(text("DROP TABLE inspection_shifts_old"))
        conn.commit()
        print(f"巡检班次表结构升级完成，迁移了 {len(rows)} 条记录")


def init_db():
    from . import models
    Base.metadata.create_all(bind=engine)
    _migrate_inspection_shifts_table()
