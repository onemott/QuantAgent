#!/usr/bin/env python3
"""
QuantAgent PostgreSQL 数据库垃圾数据清理脚本

功能说明：
---------
1. 分析模式（默认）：统计各表数据量，识别垃圾数据，输出清理报告
2. 执行模式（--execute）：真正删除垃圾数据

清理范围：
---------
- pending/error 状态超过 24 小时的 replay_sessions
- 未标记 is_saved=True 的已完成 replay_sessions 及其关联数据
- 孤立的 paper_trades（session_id 对应的 session 不存在）
- 孤立的 paper_positions
- 孤立的 equity_snapshots
- 孤立的 paper_account_replay 记录
- 过期的 backtest_results（未被任何 saved session 引用）

不会删除的数据：
-------------
- ClickHouse klines 表（本脚本不操作 ClickHouse）
- strategy_default_params（策略配置）
- strategy_param_history（参数历史）
- is_saved=True 的 replay_sessions 及其关联数据
- paper_account (id=1) 全局账户

使用方法：
--------
  # 分析模式（只显示报告，不删除）
  python cleanup_database.py

  # 执行模式（真正删除）
  python cleanup_database.py --execute

  # 自定义数据库连接
  python cleanup_database.py --db-url postgresql://user:pass@host:port/db

作者：QuantAgent Team
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("错误: 需要安装 psycopg2 模块")
    print("请运行: pip install psycopg2-binary")
    sys.exit(1)


# ANSI 颜色码
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def colored(text: str, color: str) -> str:
    """返回带颜色的文本"""
    return f"{color}{text}{Colors.END}"


def print_header(text: str) -> None:
    """打印标题"""
    print()
    print(colored("=" * 60, Colors.CYAN))
    print(colored(f"  {text}", Colors.BOLD + Colors.CYAN))
    print(colored("=" * 60, Colors.CYAN))


def print_section(text: str) -> None:
    """打印小节标题"""
    print()
    print(colored(f"▶ {text}", Colors.BOLD + Colors.BLUE))
    print(colored("-" * 40, Colors.BLUE))


def print_success(text: str) -> None:
    """打印成功消息"""
    print(colored(f"✓ {text}", Colors.GREEN))


def print_warning(text: str) -> None:
    """打印警告消息"""
    print(colored(f"⚠ {text}", Colors.YELLOW))


def print_error(text: str) -> None:
    """打印错误消息"""
    print(colored(f"✗ {text}", Colors.RED))


def print_info(text: str) -> None:
    """打印信息"""
    print(colored(f"  {text}", Colors.CYAN))


def format_number(n: int) -> str:
    """格式化数字，添加千位分隔符"""
    return f"{n:,}"


class DatabaseCleaner:
    """数据库清理器"""

    DEFAULT_DB_URL = "postgresql://quantagent:quantagent@localhost:5435/quantagent"

    def __init__(self, db_url: str = None):
        self.db_url = db_url or self.DEFAULT_DB_URL
        self.conn = None
        self.stats = {
            "tables": {},
            "garbage": {},
            "deleted": {},
        }

    def connect(self) -> bool:
        """连接数据库"""
        try:
            print_info(f"连接数据库: {self._mask_password(self.db_url)}")
            self.conn = psycopg2.connect(self.db_url)
            print_success("数据库连接成功")
            return True
        except psycopg2.Error as e:
            print_error(f"数据库连接失败: {e}")
            return False

    def _mask_password(self, url: str) -> str:
        """隐藏连接字符串中的密码"""
        import re
        return re.sub(r'://([^:]+):([^@]+)@', r'://\1:****@', url)

    def close(self) -> None:
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            print_info("数据库连接已关闭")

    def execute_query(self, query: str, params: tuple = None) -> list[dict[str, Any]]:
        """执行查询并返回结果"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def execute_count(self, query: str, params: tuple = None) -> int:
        """执行计数查询"""
        result = self.execute_query(query, params)
        return result[0]['count'] if result else 0

    def execute_update(self, query: str, params: tuple = None) -> int:
        """执行更新/删除并返回受影响行数"""
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            return cur.rowcount

    def analyze_tables(self) -> None:
        """分析各表数据量"""
        print_section("表数据量统计")

        tables = [
            "replay_sessions",
            "paper_trades",
            "paper_positions",
            "equity_snapshots",
            "paper_account_replay",
            "backtest_results",
            "trade_pairs",
            "paper_account",
            "strategy_default_params",
            "strategy_param_history",
            "risk_events",
            "agent_memories",
            "optimization_results",
            "performance_metrics",
            "audit_logs",
        ]

        max_name_len = max(len(t) for t in tables)

        for table in tables:
            try:
                count = self.execute_count(f"SELECT COUNT(*) as count FROM {table}")
                self.stats["tables"][table] = count
                status = colored(f"{format_number(count):>10}", Colors.GREEN if count > 0 else Colors.YELLOW)
                print(f"  {table:<{max_name_len}} : {status} 行")
            except psycopg2.Error as e:
                self.stats["tables"][table] = -1
                print(f"  {table:<{max_name_len}} : {colored('表不存在', Colors.RED)}")

    def identify_garbage_sessions(self) -> list[str]:
        """识别需要清理的 replay_sessions"""
        print_section("识别垃圾 replay_sessions")

        garbage_session_ids = []

        # 1. pending/error 状态超过 24 小时
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

        stale_sessions = self.execute_query("""
            SELECT replay_session_id, status, created_at
            FROM replay_sessions
            WHERE status IN ('pending', 'error', 'failed')
              AND created_at < %s
        """, (cutoff_time,))

        if stale_sessions:
            print_info(f"过期的 pending/error/failed 会话（超过24小时）: {len(stale_sessions)} 个")
            for s in stale_sessions:
                garbage_session_ids.append(s['replay_session_id'])
        else:
            print_info("没有过期的 pending/error/failed 会话")

        self.stats["garbage"]["stale_sessions"] = len(stale_sessions)

        # 2. 未保存的已完成会话
        unsaved_completed = self.execute_query("""
            SELECT replay_session_id, status, created_at
            FROM replay_sessions
            WHERE is_saved = FALSE
              AND status IN ('completed', 'running', 'paused')
        """)

        if unsaved_completed:
            print_info(f"未保存的已完成/运行中/暂停会话: {len(unsaved_completed)} 个")
            for s in unsaved_completed:
                if s['replay_session_id'] not in garbage_session_ids:
                    garbage_session_ids.append(s['replay_session_id'])
        else:
            print_info("没有未保存的已完成会话")

        self.stats["garbage"]["unsaved_sessions"] = len(unsaved_completed)

        # 统计保留的会话
        saved_count = self.execute_count("""
            SELECT COUNT(*) as count FROM replay_sessions WHERE is_saved = TRUE
        """)
        print_success(f"将保留的已保存会话: {saved_count} 个")

        return garbage_session_ids

    def identify_orphaned_data(self, garbage_session_ids: list[str]) -> dict:
        """识别孤立数据"""
        print_section("识别孤立数据")

        orphaned = {}

        # 获取所有有效的 session_id（保留的会话）
        valid_sessions = self.execute_query("""
            SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
        """)
        valid_session_ids = set(s['replay_session_id'] for s in valid_sessions)

        # 1. 孤立的 paper_trades（session_id 不在任何 replay_sessions 中，且不是 paper 模式）
        orphaned_trades = self.execute_count("""
            SELECT COUNT(*) as count FROM paper_trades
            WHERE session_id IS NOT NULL
              AND mode = 'historical_replay'
              AND session_id NOT IN (
                  SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
              )
        """)
        orphaned["paper_trades"] = orphaned_trades
        print_info(f"孤立的 paper_trades: {format_number(orphaned_trades)} 行")

        # 2. 孤立的 paper_positions
        orphaned_positions = self.execute_count("""
            SELECT COUNT(*) as count FROM paper_positions
            WHERE session_id IS NOT NULL
              AND session_id NOT IN (
                  SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
              )
        """)
        orphaned["paper_positions"] = orphaned_positions
        print_info(f"孤立的 paper_positions: {format_number(orphaned_positions)} 行")

        # 3. 孤立的 equity_snapshots
        orphaned_snapshots = self.execute_count("""
            SELECT COUNT(*) as count FROM equity_snapshots
            WHERE session_id IS NOT NULL
              AND session_id NOT IN (
                  SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
              )
        """)
        orphaned["equity_snapshots"] = orphaned_snapshots
        print_info(f"孤立的 equity_snapshots: {format_number(orphaned_snapshots)} 行")

        # 4. 孤立的 paper_account_replay
        orphaned_accounts = self.execute_count("""
            SELECT COUNT(*) as count FROM paper_account_replay
            WHERE session_id NOT IN (
                SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
            )
        """)
        orphaned["paper_account_replay"] = orphaned_accounts
        print_info(f"孤立的 paper_account_replay: {format_number(orphaned_accounts)} 行")

        # 5. 孤立的 trade_pairs（引用的 paper_trades 将被删除）
        orphaned_pairs = self.execute_count("""
            SELECT COUNT(*) as count FROM trade_pairs tp
            WHERE EXISTS (
                SELECT 1 FROM paper_trades pt
                WHERE pt.id = tp.entry_trade_id
                  AND pt.session_id IS NOT NULL
                  AND pt.mode = 'historical_replay'
                  AND pt.session_id NOT IN (
                      SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
                  )
            )
        """)
        orphaned["trade_pairs"] = orphaned_pairs
        print_info(f"关联的 trade_pairs: {format_number(orphaned_pairs)} 行")

        self.stats["garbage"]["orphaned"] = orphaned
        return orphaned

    def identify_expired_backtests(self) -> int:
        """识别过期的 backtest_results"""
        print_section("识别过期 backtest_results")

        # 被保存的 session 引用的 backtest_id
        referenced_backtests = self.execute_query("""
            SELECT DISTINCT backtest_id FROM replay_sessions
            WHERE is_saved = TRUE AND backtest_id IS NOT NULL
        """)
        referenced_ids = set(r['backtest_id'] for r in referenced_backtests)

        # 所有 backtest_results
        total_backtests = self.execute_count("SELECT COUNT(*) as count FROM backtest_results")

        if referenced_ids:
            # 未被引用的 backtest_results
            expired_count = self.execute_count("""
                SELECT COUNT(*) as count FROM backtest_results
                WHERE id NOT IN %s
            """, (tuple(referenced_ids),))
        else:
            expired_count = total_backtests

        print_info(f"总 backtest_results: {format_number(total_backtests)} 行")
        print_info(f"被保存会话引用: {format_number(len(referenced_ids))} 个")
        print_info(f"未被引用（可清理）: {format_number(expired_count)} 行")

        self.stats["garbage"]["expired_backtests"] = expired_count
        return expired_count

    def print_cleanup_summary(self, garbage_session_ids: list[str]) -> None:
        """打印清理摘要"""
        print_header("清理摘要报告")

        total_garbage = 0

        # replay_sessions
        sessions_to_delete = len(garbage_session_ids)
        total_garbage += sessions_to_delete
        print(f"  replay_sessions 待删除: {colored(format_number(sessions_to_delete), Colors.RED)} 行")

        # 孤立数据
        orphaned = self.stats["garbage"].get("orphaned", {})
        for table, count in orphaned.items():
            total_garbage += count
            print(f"  {table} 待删除: {colored(format_number(count), Colors.RED)} 行")

        # 过期 backtest
        expired_backtests = self.stats["garbage"].get("expired_backtests", 0)
        total_garbage += expired_backtests
        print(f"  backtest_results 待删除: {colored(format_number(expired_backtests), Colors.RED)} 行")

        print()
        print(colored(f"  总计将删除: {format_number(total_garbage)} 行数据", Colors.BOLD + Colors.YELLOW))

        # 提示
        print()
        print_warning("以上为分析结果，未执行任何删除操作")
        print_info("如需执行删除，请运行: python cleanup_database.py --execute")

    def execute_cleanup(self, garbage_session_ids: list[str]) -> None:
        """执行清理操作"""
        print_header("执行数据清理")

        print_warning("即将删除数据，此操作不可逆！")
        print()

        try:
            # 开始事务
            self.conn.autocommit = False

            deleted_total = 0

            # 1. 删除 trade_pairs（先删子表）
            print_section("删除 trade_pairs")
            deleted = self.execute_update("""
                DELETE FROM trade_pairs tp
                WHERE EXISTS (
                    SELECT 1 FROM paper_trades pt
                    WHERE pt.id = tp.entry_trade_id
                      AND pt.session_id IS NOT NULL
                      AND pt.mode = 'historical_replay'
                      AND pt.session_id NOT IN (
                          SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
                      )
                )
            """)
            self.stats["deleted"]["trade_pairs"] = deleted
            deleted_total += deleted
            print_success(f"删除 trade_pairs: {format_number(deleted)} 行")

            # 2. 删除 paper_trades
            print_section("删除 paper_trades")
            deleted = self.execute_update("""
                DELETE FROM paper_trades
                WHERE session_id IS NOT NULL
                  AND mode = 'historical_replay'
                  AND session_id NOT IN (
                      SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
                  )
            """)
            self.stats["deleted"]["paper_trades"] = deleted
            deleted_total += deleted
            print_success(f"删除 paper_trades: {format_number(deleted)} 行")

            # 3. 删除 paper_positions
            print_section("删除 paper_positions")
            deleted = self.execute_update("""
                DELETE FROM paper_positions
                WHERE session_id IS NOT NULL
                  AND session_id NOT IN (
                      SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
                  )
            """)
            self.stats["deleted"]["paper_positions"] = deleted
            deleted_total += deleted
            print_success(f"删除 paper_positions: {format_number(deleted)} 行")

            # 4. 删除 equity_snapshots
            print_section("删除 equity_snapshots")
            deleted = self.execute_update("""
                DELETE FROM equity_snapshots
                WHERE session_id IS NOT NULL
                  AND session_id NOT IN (
                      SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
                  )
            """)
            self.stats["deleted"]["equity_snapshots"] = deleted
            deleted_total += deleted
            print_success(f"删除 equity_snapshots: {format_number(deleted)} 行")

            # 5. 删除 paper_account_replay
            print_section("删除 paper_account_replay")
            deleted = self.execute_update("""
                DELETE FROM paper_account_replay
                WHERE session_id NOT IN (
                    SELECT replay_session_id FROM replay_sessions WHERE is_saved = TRUE
                )
            """)
            self.stats["deleted"]["paper_account_replay"] = deleted
            deleted_total += deleted
            print_success(f"删除 paper_account_replay: {format_number(deleted)} 行")

            # 6. 删除未被引用的 backtest_results
            print_section("删除 backtest_results")
            # 先获取被保存会话引用的 backtest_id
            referenced = self.execute_query("""
                SELECT DISTINCT backtest_id FROM replay_sessions
                WHERE is_saved = TRUE AND backtest_id IS NOT NULL
            """)
            referenced_ids = [r['backtest_id'] for r in referenced]

            if referenced_ids:
                deleted = self.execute_update("""
                    DELETE FROM backtest_results WHERE id NOT IN %s
                """, (tuple(referenced_ids),))
            else:
                deleted = self.execute_update("DELETE FROM backtest_results")

            self.stats["deleted"]["backtest_results"] = deleted
            deleted_total += deleted
            print_success(f"删除 backtest_results: {format_number(deleted)} 行")

            # 7. 最后删除 replay_sessions（父表）
            print_section("删除 replay_sessions")
            deleted = self.execute_update("""
                DELETE FROM replay_sessions WHERE is_saved = FALSE
            """)
            self.stats["deleted"]["replay_sessions"] = deleted
            deleted_total += deleted
            print_success(f"删除 replay_sessions: {format_number(deleted)} 行")

            # 提交事务
            self.conn.commit()

            print_header("清理完成")
            print_success(f"总计删除: {format_number(deleted_total)} 行数据")

            # 打印最终统计
            self._print_final_stats()

        except psycopg2.Error as e:
            self.conn.rollback()
            print_error(f"清理过程中发生错误，已回滚: {e}")
            raise

    def _print_final_stats(self) -> None:
        """打印清理后的最终统计"""
        print_section("清理后表数据量")

        tables = [
            "replay_sessions",
            "paper_trades",
            "paper_positions",
            "equity_snapshots",
            "paper_account_replay",
            "backtest_results",
            "trade_pairs",
        ]

        max_name_len = max(len(t) for t in tables)

        for table in tables:
            try:
                count = self.execute_count(f"SELECT COUNT(*) as count FROM {table}")
                deleted = self.stats["deleted"].get(table, 0)
                status = colored(f"{format_number(count):>10}", Colors.GREEN)
                deleted_str = colored(f"(-{format_number(deleted)})", Colors.RED) if deleted > 0 else ""
                print(f"  {table:<{max_name_len}} : {status} 行 {deleted_str}")
            except psycopg2.Error:
                pass

    def run(self, execute: bool = False) -> int:
        """运行清理流程"""
        print_header("QuantAgent 数据库垃圾清理工具")

        if execute:
            print_warning("*** 执行模式 - 将真正删除数据 ***")
        else:
            print_info("分析模式 - 只显示报告，不删除数据")

        # 连接数据库
        if not self.connect():
            return 1

        try:
            # 分析表数据量
            self.analyze_tables()

            # 识别垃圾 sessions
            garbage_session_ids = self.identify_garbage_sessions()

            # 识别孤立数据
            self.identify_orphaned_data(garbage_session_ids)

            # 识别过期 backtests
            self.identify_expired_backtests()

            if execute:
                # 执行清理
                self.execute_cleanup(garbage_session_ids)
            else:
                # 显示摘要
                self.print_cleanup_summary(garbage_session_ids)

            return 0

        except Exception as e:
            print_error(f"发生错误: {e}")
            return 1

        finally:
            self.close()


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="QuantAgent PostgreSQL 数据库垃圾数据清理脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 分析模式（只显示报告，不删除）
  python cleanup_database.py

  # 执行模式（真正删除）
  python cleanup_database.py --execute

  # 自定义数据库连接
  python cleanup_database.py --db-url postgresql://user:pass@host:port/db
        """
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="执行删除操作（默认为分析模式，只显示报告）"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="分析模式（与默认行为相同，只显示报告）"
    )

    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help=f"数据库连接 URL（默认: {DatabaseCleaner.DEFAULT_DB_URL}）"
    )

    args = parser.parse_args()

    # --dry-run 和 --execute 互斥，--dry-run 优先
    execute = args.execute and not args.dry_run

    cleaner = DatabaseCleaner(db_url=args.db_url)
    sys.exit(cleaner.run(execute=execute))


if __name__ == "__main__":
    main()

