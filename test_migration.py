#!/usr/bin/env python3
"""测试数据库迁移功能：从旧表结构迁移到新表结构"""
import sqlite3
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "pump_inspection.db")

sys.path.insert(0, PROJECT_ROOT)


def create_old_structure_db():
    """创建旧结构数据库（shift_id 全局唯一）"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''
    CREATE TABLE inspection_shifts (
        id INTEGER PRIMARY KEY,
        batch_id INTEGER,
        shift_id TEXT NOT NULL UNIQUE,
        shift_date DATETIME NOT NULL,
        shift_type TEXT,
        inspector TEXT,
        start_time DATETIME,
        end_time DATETIME,
        equipment_checked TEXT,
        raw_data TEXT
    )
    ''')
    
    for i in range(3):
        c.execute(f"""
        INSERT INTO inspection_shifts (batch_id, shift_id, shift_date, shift_type, inspector)
        VALUES (1, 'SHIFT-OLD-{i:03d}', '2026-06-01', '白班', '测试员{i}')
        """)
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY,
        batch_name TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        import_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'processing',
        total_records INTEGER DEFAULT 0,
        anomaly_count INTEGER DEFAULT 0,
        reviewed_count INTEGER DEFAULT 0,
        source_file TEXT,
        notes TEXT
    )
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS equipment_ledger (
        id INTEGER PRIMARY KEY,
        device_id TEXT NOT NULL UNIQUE,
        device_name TEXT NOT NULL,
        location TEXT NOT NULL,
        install_date DATETIME,
        manufacturer TEXT,
        model TEXT,
        pressure_low_limit REAL DEFAULT 0.1,
        pressure_high_limit REAL DEFAULT 1.0,
        status TEXT DEFAULT 'active',
        raw_data TEXT
    )
    ''')
    c.execute('INSERT INTO batches (batch_name, rule_version) VALUES ("旧批次", "v1")')
    
    conn.commit()
    conn.close()
    print("✅ 旧结构数据库创建完成，包含 3 条巡检班次记录")


def verify_migration():
    """验证迁移结果"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('PRAGMA index_list(inspection_shifts)')
    indexes = c.fetchall()
    index_names = [idx[1] if len(idx) > 1 else idx[0] for idx in indexes]
    print(f"当前索引: {index_names}")
    
    has_unique_index = len(index_names) >= 1
    assert has_unique_index, "迁移后应该包含唯一索引"
    
    c.execute('SELECT shift_id, inspector FROM inspection_shifts ORDER BY id')
    rows = c.fetchall()
    print(f"迁移后的记录数: {len(rows)}")
    assert len(rows) == 3, f"应该迁移 3 条记录，实际 {len(rows)} 条"
    for row in rows:
        print(f"  {row[0]} - {row[1]}")
    
    try:
        c.execute("""
        INSERT INTO inspection_shifts (batch_id, shift_id, shift_date, shift_type, inspector)
        VALUES (2, 'SHIFT-OLD-001', '2026-06-02', '夜班', '新测试员')
        """)
        print("✅ 不同批次相同 shift_id 插入成功")
    except Exception as e:
        print(f"❌ 插入失败: {e}")
        raise AssertionError("不同批次应该可以插入相同 shift_id")
    
    try:
        c.execute("""
        INSERT INTO inspection_shifts (batch_id, shift_id, shift_date, shift_type, inspector)
        VALUES (1, 'SHIFT-OLD-001', '2026-06-02', '夜班', '测试冲突')
        """)
        conn.rollback()
        raise AssertionError("同一批次相同 shift_id 应该失败但成功了")
    except sqlite3.IntegrityError as e:
        print(f"✅ 同一批次相同 shift_id 正确阻止: {type(e).__name__}")
        conn.rollback()
    
    conn.close()


def main():
    print("=" * 60)
    print("测试数据库迁移功能")
    print("=" * 60)
    
    print("\n1. 创建旧结构数据库（模拟用户已有数据）")
    create_old_structure_db()
    
    print("\n2. 运行 init-db 触发迁移")
    from pump_inspection import init_db
    init_db()
    print("✅ init-db 完成")
    
    print("\n3. 验证迁移后数据和约束")
    verify_migration()
    
    print("\n" + "=" * 60)
    print("✅ 数据库迁移测试全部通过！")
    print("=" * 60)
    
    os.remove(DB_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
