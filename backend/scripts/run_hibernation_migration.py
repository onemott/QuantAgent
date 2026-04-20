"""
执行策略休眠与复活机制的数据库迁移脚本
"""
import psycopg2
from psycopg2 import sql

# 数据库连接配置
DB_CONFIG = {
    "host": "localhost",
    "port": 5435,
    "user": "quantagent",
    "password": "quantagent",
    "dbname": "quantagent"
}

# SQL 迁移语句
MIGRATION_SQL = """
-- Add hibernation and revival columns to selection_history for strategy sleep/revive mechanism

-- Add hibernating_strategy_ids column
ALTER TABLE selection_history ADD COLUMN IF NOT EXISTS hibernating_strategy_ids JSONB DEFAULT NULL;

-- Add revived_strategy_ids column
ALTER TABLE selection_history ADD COLUMN IF NOT EXISTS revived_strategy_ids JSONB DEFAULT NULL;

-- Add revival_reasons column
ALTER TABLE selection_history ADD COLUMN IF NOT EXISTS revival_reasons JSONB DEFAULT NULL;

-- Add comments for documentation
COMMENT ON COLUMN selection_history.hibernating_strategy_ids IS '当前处于休眠状态的策略ID列表';
COMMENT ON COLUMN selection_history.revived_strategy_ids IS '本轮被复活的策略ID列表';
COMMENT ON COLUMN selection_history.revival_reasons IS '复活原因字典';
"""

VERIFICATION_SQL = """
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'selection_history'
AND column_name IN ('hibernating_strategy_ids', 'revived_strategy_ids', 'revival_reasons')
ORDER BY column_name;
"""


def run_migration():
    """执行数据库迁移"""
    conn = None
    try:
        print("=" * 60)
        print("策略休眠与复活机制 - 数据库迁移")
        print("=" * 60)
        
        # 连接数据库
        print(f"\n[1] 连接数据库: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        cursor = conn.cursor()
        print("    ✓ 数据库连接成功")
        
        # 执行迁移
        print("\n[2] 执行 SQL 迁移脚本...")
        cursor.execute(MIGRATION_SQL)
        conn.commit()
        print("    ✓ SQL 迁移执行成功")
        
        # 验证字段
        print("\n[3] 验证新增字段...")
        cursor.execute(VERIFICATION_SQL)
        results = cursor.fetchall()
        
        if results:
            print("    ✓ 新增字段已成功添加:")
            for row in results:
                column_name, data_type, is_nullable = row
                print(f"      - {column_name}: {data_type} (nullable: {is_nullable})")
        else:
            print("    ✗ 未找到新增字段，请检查迁移是否成功")
        
        cursor.close()
        print("\n" + "=" * 60)
        print("迁移完成!")
        print("=" * 60)
        return True
        
    except psycopg2.OperationalError as e:
        print(f"\n✗ 数据库连接失败: {e}")
        return False
    except psycopg2.Error as e:
        print(f"\n✗ SQL 执行错误: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e:
        print(f"\n✗ 未知错误: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    success = run_migration()
    exit(0 if success else 1)
