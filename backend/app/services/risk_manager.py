"""
Risk Manager — 风控规则引擎
负责对每笔模拟下单进行前置风控检查，防止过度集中仓位、账户大幅回撤和单日巨额亏损。

风控规则：
  1. 全局熔断 (Kill Switch)：手动或自动触发，停止所有买入/卖空
  2. 异常交易拦截 (Fat Finger)：价格偏离市场价过大
  3. 单仓仓位价值不超过账户总值的 MAX_SINGLE_POSITION_PCT
  4. 账户总回撤超过 MAX_TOTAL_DRAWDOWN_PCT 时熔断
  5. 当日亏损超过 MAX_DAILY_LOSS_PCT 时暂停买入
  6. 余额/保证金充足性检查 (支持杠杆与做空)
"""

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Tuple, Dict, Any, Optional

from sqlalchemy import select, func as sqlfunc

from app.services.database import get_db, redis_get, redis_set
from app.models.db_models import RiskEvent, PaperTrade, PaperAccount

logger = logging.getLogger(__name__)

# ── 风控阈值常量 ─────────────────────────────────────────────────────────────
MAX_SINGLE_POSITION_PCT: float = 0.20   # 单仓不超过账户总值的 20% (放宽以支持测试)
MAX_TOTAL_DRAWDOWN_PCT: float  = 0.15   # 总回撤达 15% 熔断
MAX_DAILY_LOSS_PCT: float      = 0.05   # 当日亏损达账户总值 5% 暂停买入
PRICE_DEVIATION_PCT: float     = 0.05   # 价格偏离超过 5% 视为异常 (Fat Finger)
INITIAL_BALANCE: Decimal       = Decimal("100000.0")
FEE_RATE: Decimal              = Decimal("0.001")
# MAX_LEVERAGE removed in favor of dynamic calculation

# Redis 缓存 key
REDIS_PEAK_BALANCE_KEY = "risk:peak_balance"
REDIS_DAILY_LOSS_KEY   = "risk:daily_loss:{date}"
REDIS_KILL_SWITCH_KEY  = "risk:kill_switch"  # Boolean (0 or 1)

# Hard to borrow list (Simulation)
HARD_TO_BORROW_SYMBOLS = ["DOGEUSDT", "SHIBUSDT"] 


class RiskCheckResult:
    """风控检查结果"""

    def __init__(self, allowed: bool, rule: Optional[str] = None, reason: str = ""):
        self.allowed = allowed
        self.rule    = rule    # 触发的规则名称
        self.reason  = reason  # 拒绝原因（允许时为空）

    def __repr__(self):
        return f"RiskCheckResult(allowed={self.allowed}, rule={self.rule}, reason={self.reason!r})"


class RiskManager:
    """
    单例风控引擎。
    所有风控方法均为 async，调用时需 await。
    """

    # ── 主入口：下单前检查 ────────────────────────────────────────────────────
    async def check_order(
        self,
        symbol: str,
        side: str,            # "BUY" | "SELL"
        quantity: float,
        price: float,
        current_balance: float,    # 当前可用 USDT 余额
        current_positions: Dict[str, float],  # {symbol: quantity} (负数表示空仓)
        total_portfolio_value: float,          # 总账户价值（权益 Equity）
        market_price: Optional[float] = None,  # 当前市场价 (用于 Fat Finger 检查)
        leverage: int = 1,
    ) -> RiskCheckResult:
        """
        综合风控检查入口，按规则优先级依次检查。
        """
        side = side.upper()
        quantity_dec = Decimal(str(quantity))
        price_dec = Decimal(str(price))
        order_value = quantity_dec * price_dec
        
        # ── 规则 0：全局熔断 (Kill Switch) ────────────────────────────────────
        kill_switch = await redis_get(REDIS_KILL_SWITCH_KEY)
        if kill_switch:
            return RiskCheckResult(allowed=False, rule="KILL_SWITCH", reason="Global Kill Switch Activated")

        # ── 规则 0.5：异常交易拦截 (Fat Finger) ──────────────────────────────
        if market_price and market_price > 0:
            deviation = abs(price - market_price) / market_price
            if deviation > PRICE_DEVIATION_PCT:
                reason = (
                    f"价格偏离过大 (Fat Finger)：委托价 {price} 与市场价 {market_price} "
                    f"偏离 {deviation*100:.2f}% (阈值 {PRICE_DEVIATION_PCT*100:.0f}%)"
                )
                await self._log_risk_event(symbol, "FAT_FINGER", True, {
                    "order_price": price,
                    "market_price": market_price,
                    "deviation_pct": round(deviation * 100, 2)
                })
                return RiskCheckResult(allowed=False, rule="FAT_FINGER", reason=reason)
            
            # 大单拆分检查
            # 假设 ADV (Average Daily Volume) 为 100M (模拟值)
            # 实际应从数据库或 MarketAnalysis 获取
            ADV = 100_000_000 
            if float(order_value) > ADV * 0.01:
                 # 警告但不一定拒绝，或者要求拆单
                 # 这里我们简单记录日志并拒绝
                 reason = f"订单价值 ${float(order_value):.2f} 超过日均成交量 1% (大单拦截)"
                 return RiskCheckResult(allowed=False, rule="LARGE_ORDER", reason=reason)

        # ── 杠杆检查 (Tiered Margin) ──────────────────────────────────────────
        max_leverage = self._calculate_dynamic_leverage(total_portfolio_value)
        if leverage > max_leverage:
             return RiskCheckResult(allowed=False, rule="MAX_LEVERAGE", reason=f"Leverage {leverage}x exceeds dynamic limit {max_leverage}x (Portfolio: ${total_portfolio_value:,.0f})")

        # ── 规则 1：单仓上限 (针对开仓) ───────────────────────────────────────
        # 无论是做多 (BUY) 还是 做空 (SELL when pos <= 0)，只要是增加风险敞口
        current_pos_qty = Decimal(str(current_positions.get(symbol, 0)))
        
        is_opening = False
        if side == "BUY" and current_pos_qty >= 0: # 加多
            is_opening = True
            new_qty = current_pos_qty + quantity_dec
        elif side == "SELL" and current_pos_qty <= 0: # 加空
            is_opening = True
            new_qty = current_pos_qty - quantity_dec
        else:
            # 减仓或平仓，通常允许，除非是为了反手
            # 简化：如果是减仓，不检查单仓上限
            pass

        if is_opening:
            new_pos_value = abs(new_qty) * price_dec
            max_allowed = Decimal(str(total_portfolio_value)) * Decimal(str(MAX_SINGLE_POSITION_PCT))
            
            if new_pos_value > max_allowed:
                reason = (
                    f"单仓超限：{symbol} 持仓将达 ${float(new_pos_value):.2f}，"
                    f"超过账户总值 {MAX_SINGLE_POSITION_PCT*100:.0f}% 上限 ${float(max_allowed):.2f}"
                )
                await self._log_risk_event(symbol, "MAX_SINGLE_POSITION", True, {
                    "order_value": float(order_value),
                    "new_pos_value": float(new_pos_value),
                    "max_allowed": float(max_allowed),
                })
                return RiskCheckResult(allowed=False, rule="MAX_SINGLE_POSITION", reason=reason)

        # ── 规则 2：总回撤熔断 ────────────────────────────────────────────────
        # 若触发熔断，仅允许平仓 (Close positions)，禁止开仓
        if is_opening:
            peak = await self._get_peak_balance(total_portfolio_value)
            if peak > 0:
                drawdown = (peak - total_portfolio_value) / peak
                if drawdown >= MAX_TOTAL_DRAWDOWN_PCT:
                    reason = (
                        f"账户回撤熔断：当前回撤 {drawdown*100:.2f}%，"
                        f"超过熔断阈值 {MAX_TOTAL_DRAWDOWN_PCT*100:.0f}%，禁止新开仓"
                    )
                    await self._log_risk_event(symbol, "DRAWDOWN_HALT", True, {
                        "peak_balance": peak,
                        "current_value": total_portfolio_value,
                        "drawdown_pct": round(drawdown * 100, 2),
                    })
                    return RiskCheckResult(allowed=False, rule="DRAWDOWN_HALT", reason=reason)

        # ── 规则 3：单日亏损上限 ──────────────────────────────────────────────
        if is_opening:
            daily_pnl = await self._get_today_realized_pnl()
            if daily_pnl < 0:
                daily_loss_pct = abs(daily_pnl) / float(INITIAL_BALANCE)
                if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
                    reason = (
                        f"单日亏损暂停：今日已亏损 ${abs(daily_pnl):.2f} "
                        f"({daily_loss_pct*100:.2f}%)，超过日限 {MAX_DAILY_LOSS_PCT*100:.0f}%，禁止新开仓"
                    )
                    await self._log_risk_event(symbol, "DAILY_LOSS_HALT", True, {
                        "daily_pnl": daily_pnl,
                        "daily_loss_pct": round(daily_loss_pct * 100, 2),
                    })
                    return RiskCheckResult(allowed=False, rule="DAILY_LOSS_HALT", reason=reason)

        # ── 规则 4：余额/保证金充足性 ────────────────────────────────────────
        # 这里的 balance 是可用余额。
        # 开仓成本 = (Order Value / Leverage) + Fee
        # Fee 通常按全额计算
        if is_opening:
            margin_required = order_value / Decimal(leverage)
            fee = order_value * FEE_RATE
            total_cost = margin_required + fee
            
            if Decimal(str(current_balance)) < total_cost:
                reason = (
                    f"余额不足：需 ${float(total_cost):.2f} (Margin ${float(margin_required):.2f} + Fee ${float(fee):.2f})，"
                    f"可用 ${current_balance:.2f}"
                )
                return RiskCheckResult(allowed=False, rule="INSUFFICIENT_BALANCE", reason=reason)
        
        # ── 做空风控 (Locate) ────────────────────────────────────────────────
        if side == "SELL" and is_opening:
             # 模拟借币检查
             if symbol in HARD_TO_BORROW_SYMBOLS:
                 # 50% chance to fail locate for HTB symbols
                 import random
                 if random.random() < 0.5:
                     reason = f"融券失败 (Locate Failed): {symbol} 属于难借资产，当前无券源"
                     await self._log_risk_event(symbol, "LOCATE_FAILED", True, {"symbol": symbol})
                     return RiskCheckResult(allowed=False, rule="LOCATE_FAILED", reason=reason)

        # 所有规则通过
        return RiskCheckResult(allowed=True)

    def _calculate_dynamic_leverage(self, portfolio_value: float) -> int:
        """
        Tiered Margin Logic:
        < $10,000  -> 3x
        < $50,000  -> 2x
        >= $50,000 -> 1x
        """
        if portfolio_value < 10000:
            return 3
        elif portfolio_value < 50000:
            return 2
        else:
            return 1

    # ── 熔断控制 ─────────────────────────────────────────────────────────────
    async def trigger_kill_switch(self):
        """手动触发熔断"""
        await redis_set(REDIS_KILL_SWITCH_KEY, 1)
        logger.warning("GLOBAL KILL SWITCH ACTIVATED")
        # TODO: Publish event to cancel all orders

    async def reset_kill_switch(self):
        """重置熔断"""
        await redis_set(REDIS_KILL_SWITCH_KEY, 0)
        logger.info("Global Kill Switch Reset")

    async def check_kill_switch(self) -> bool:
        """检查熔断状态"""
        val = await redis_get(REDIS_KILL_SWITCH_KEY)
        return bool(val)

    # ── 逼空保护 (Short Squeeze Guard) ───────────────────────────────────────
    async def check_short_squeeze(self, symbol: str, current_price: float, avg_price: float, quantity: float) -> bool:
        """
        检查空头仓位是否遭遇逼空 (Short Squeeze)。
        规则：空单亏损 > 15% (Stop Loss) 建议强平。
        返回 True 表示建议平仓。
        """
        if quantity >= 0: # Not a short position
            return False
            
        # Short PnL = (Entry - Current) / Entry
        # Loss > 15% means (Entry - Current) / Entry < -0.15
        # => Entry - Current < -0.15 * Entry
        # => Current - Entry > 0.15 * Entry
        # => Current > 1.15 * Entry
        
        threshold = 1.15
        if current_price > avg_price * threshold:
            loss_pct = (current_price - avg_price) / avg_price * 100
            await self._log_risk_event(symbol, "SHORT_SQUEEZE_GUARD", True, {
                "avg_price": float(avg_price),
                "current_price": current_price,
                "loss_pct": round(loss_pct, 2)
            })
            logger.warning(f"Short Squeeze Alert: {symbol} lost {loss_pct:.2f}%. Suggesting FORCE CLOSE.")
            return True
            
        return False

    # ── 更新峰值余额（每次成功交易后调用）────────────────────────────────────
    async def update_peak_balance(self, current_total_value: float) -> None:
        """若当前总资产超过历史峰值，更新峰值记录。"""
        peak = await redis_get(REDIS_PEAK_BALANCE_KEY)
        peak_val = float(peak) if peak is not None else float(INITIAL_BALANCE)
        if current_total_value > peak_val:
            await redis_set(REDIS_PEAK_BALANCE_KEY, current_total_value, ttl=86400 * 365)

    # ── 获取账户风控状态（供前端展示）────────────────────────────────────────
    async def get_risk_status(self, total_portfolio_value: float) -> Dict[str, Any]:
        """返回当前账户的风控指标概览。"""
        peak = await self._get_peak_balance(total_portfolio_value)
        drawdown = (peak - total_portfolio_value) / peak if peak > 0 else 0.0
        daily_pnl = await self._get_today_realized_pnl()
        kill_switch = await redis_get(REDIS_KILL_SWITCH_KEY)

        return {
            "peak_balance":         round(peak, 2),
            "current_value":        round(total_portfolio_value, 2),
            "total_drawdown_pct":   round(drawdown * 100, 2),
            "drawdown_limit_pct":   MAX_TOTAL_DRAWDOWN_PCT * 100,
            "drawdown_breached":    drawdown >= MAX_TOTAL_DRAWDOWN_PCT,
            "daily_pnl":            round(daily_pnl, 2),
            "daily_loss_limit_pct": MAX_DAILY_LOSS_PCT * 100,
            "daily_loss_breached":  daily_pnl < 0 and abs(daily_pnl) / float(INITIAL_BALANCE) >= MAX_DAILY_LOSS_PCT,
            "single_position_limit_pct": MAX_SINGLE_POSITION_PCT * 100,
            "max_leverage":         self._calculate_dynamic_leverage(total_portfolio_value),
            "kill_switch_active":   bool(kill_switch),
        }

    # ── 获取风控事件历史 ──────────────────────────────────────────────────────
    async def get_risk_events(self, limit: int = 20):
        """返回最新风控事件列表。"""
        async with get_db() as session:
            stmt = (
                select(RiskEvent)
                .order_by(RiskEvent.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            {
                "id":        row.id,
                "symbol":    row.symbol,
                "rule":      row.rule,
                "triggered": row.triggered,
                "detail":    row.detail,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    # ── 内部辅助方法 ──────────────────────────────────────────────────────────
    async def _get_peak_balance(self, current_value: float) -> float:
        """从 Redis 获取历史峰值余额，若无记录则使用初始余额。"""
        peak = await redis_get(REDIS_PEAK_BALANCE_KEY)
        if peak is None:
            await redis_set(REDIS_PEAK_BALANCE_KEY, float(INITIAL_BALANCE), ttl=86400 * 365)
            return float(INITIAL_BALANCE)
        peak_val = float(peak)
        # 若当前值更高则更新
        if current_value > peak_val:
            await redis_set(REDIS_PEAK_BALANCE_KEY, current_value, ttl=86400 * 365)
            return current_value
        return peak_val

    async def _get_today_realized_pnl(self) -> float:
        """计算今日已实现盈亏（仅平仓交易含 pnl）。"""
        today_key = REDIS_DAILY_LOSS_KEY.format(
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        cached = await redis_get(today_key)
        if cached is not None:
            return float(cached)

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        try:
            async with get_db() as session:
                # 统计所有已平仓的 PnL (pnl is not null)
                stmt = (
                    select(sqlfunc.coalesce(sqlfunc.sum(PaperTrade.pnl), 0))
                    .where(PaperTrade.pnl.isnot(None))
                    .where(PaperTrade.created_at >= today_start)
                )
                result = await session.execute(stmt)
                total_pnl = float(result.scalar() or 0)
        except Exception as e:
            logger.warning(f"Failed to query today PnL: {e}")
            total_pnl = 0.0

        await redis_set(today_key, total_pnl, ttl=300)  # 5 分钟缓存
        return total_pnl

    async def _log_risk_event(
        self,
        symbol: str,
        rule: str,
        triggered: bool,
        detail: Dict[str, Any],
    ) -> None:
        """将风控事件写入 PostgreSQL risk_events 表。"""
        try:
            async with get_db() as session:
                event = RiskEvent(
                    symbol=symbol,
                    rule=rule,
                    triggered=triggered,
                    detail=detail,
                )
                session.add(event)
        except Exception as e:
            logger.warning(f"Failed to log risk event: {e}")


# 单例实例
risk_manager = RiskManager()
