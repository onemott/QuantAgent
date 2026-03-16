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
from app.core.config import settings
from app.models.db_models import RiskEvent, PaperTrade, PaperAccount

logger = logging.getLogger(__name__)

# ── Redis 缓存 key ─────────────────────────────────────────────────────────────
REDIS_PEAK_BALANCE_KEY = "risk:peak_balance"
REDIS_DAILY_LOSS_KEY   = "risk:daily_loss:{date}"
REDIS_KILL_SWITCH_KEY  = "risk:kill_switch"  # Boolean (0 or 1)
REDIS_RISK_CONFIG_KEY  = "risk:config"      # JSON dict

INITIAL_BALANCE: Decimal       = Decimal("100000.0")
FEE_RATE: Decimal              = Decimal("0.001")

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

    # ── 阈值获取 (支持热更新) ──────────────────────────────────────────────────
    async def get_config(self) -> Dict[str, float]:
        """获取当前风控配置，优先从 Redis 获取，否则使用 settings"""
        cached = await redis_get(REDIS_RISK_CONFIG_KEY)
        if cached:
            try:
                import json
                return json.loads(cached)
            except Exception:
                pass
        
        return {
            "MAX_SINGLE_POSITION_PCT": settings.MAX_SINGLE_POSITION_PCT,
            "MAX_TOTAL_DRAWDOWN_PCT": settings.MAX_TOTAL_DRAWDOWN_PCT,
            "MAX_DAILY_LOSS_PCT": settings.MAX_DAILY_LOSS_PCT,
            "PRICE_DEVIATION_PCT": settings.PRICE_DEVIATION_PCT,
            "MAX_VOLATILITY_THRESHOLD": 0.80, # 80% 年化波动率阈值
        }

    async def update_config(self, new_config: Dict[str, float]):
        """更新风控配置到 Redis"""
        import json
        await redis_set(REDIS_RISK_CONFIG_KEY, json.dumps(new_config))
        logger.info(f"Risk config updated: {new_config}")

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

        # 获取当前配置
        config = await self.get_config()
        
        # ── 规则 0：全局熔断 (Kill Switch) ────────────────────────────────────
        kill_switch = await redis_get(REDIS_KILL_SWITCH_KEY)
        if kill_switch:
            return RiskCheckResult(allowed=False, rule="KILL_SWITCH", reason="Global Kill Switch Activated")

        # ── 规则 0.1：波动率激增拦截 (Anti-Black Swan) ────────────────────────
        if is_opening:
            # 获取当前资产的波动率（模拟，实际应由 MarketAnalysis 提供）
            # 这里我们简单模拟：若当前价格相对于 24h 移动平均偏离超过 15%，视为异常波动
            volatility_spike = await self._check_tail_risk(symbol, market_price)
            if volatility_spike:
                reason = f"波动率激增 (Tail Risk)：检测到 {symbol} 处于极端波动期，强制进入避险模式（转换为稳定币/禁止开仓）"
                await self._log_risk_event(symbol, "TAIL_RISK_HALT", True, {"symbol": symbol, "market_price": market_price})
                return RiskCheckResult(allowed=False, rule="TAIL_RISK_HALT", reason=reason)

        # ── 规则 0.5：异常交易拦截 (Fat Finger) ──────────────────────────────
        if market_price and market_price > 0:
            deviation = abs(price - market_price) / market_price
            price_dev_limit = config.get("PRICE_DEVIATION_PCT", 0.05)
            if deviation > price_dev_limit:
                reason = (
                    f"价格偏离过大 (Fat Finger)：委托价 {price} 与市场价 {market_price} "
                    f"偏离 {deviation*100:.2f}% (阈值 {price_dev_limit*100:.0f}%)"
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
            single_pos_limit = config.get("MAX_SINGLE_POSITION_PCT", 0.20)
            max_allowed = Decimal(str(total_portfolio_value)) * Decimal(str(single_pos_limit))
            
            if new_pos_value > max_allowed:
                reason = (
                    f"单仓超限：{symbol} 持仓将达 ${float(new_pos_value):.2f}，"
                    f"超过账户总值 {single_pos_limit*100:.0f}% 上限 ${float(max_allowed):.2f}"
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
                drawdown_limit = config.get("MAX_TOTAL_DRAWDOWN_PCT", 0.15)
                if drawdown >= drawdown_limit:
                    reason = (
                        f"账户回撤熔断：当前回撤 {drawdown*100:.2f}%，"
                        f"超过熔断阈值 {drawdown_limit*100:.0f}%，禁止新开仓"
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
                daily_loss_limit = config.get("MAX_DAILY_LOSS_PCT", 0.05)
                if daily_loss_pct >= daily_loss_limit:
                    reason = (
                        f"单日亏损暂停：今日已亏损 ${abs(daily_pnl):.2f} "
                        f"({daily_loss_pct*100:.2f}%)，超过日限 {daily_loss_limit*100:.0f}%，禁止新开仓"
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
        config = await self.get_config()
        peak = await self._get_peak_balance(total_portfolio_value)
        drawdown = (peak - total_portfolio_value) / peak if peak > 0 else 0.0
        daily_pnl = await self._get_today_realized_pnl()
        kill_switch = await redis_get(REDIS_KILL_SWITCH_KEY)

        drawdown_limit = config.get("MAX_TOTAL_DRAWDOWN_PCT", 0.15)
        daily_loss_limit = config.get("MAX_DAILY_LOSS_PCT", 0.05)
        single_pos_limit = config.get("MAX_SINGLE_POSITION_PCT", 0.20)

        return {
            "peak_balance":         round(peak, 2),
            "current_value":        round(total_portfolio_value, 2),
            "total_drawdown_pct":   round(drawdown * 100, 2),
            "drawdown_limit_pct":   drawdown_limit * 100,
            "drawdown_breached":    drawdown >= drawdown_limit,
            "daily_pnl":            round(daily_pnl, 2),
            "daily_loss_limit_pct": daily_loss_limit * 100,
            "daily_loss_breached":  daily_pnl < 0 and abs(daily_pnl) / float(INITIAL_BALANCE) >= daily_loss_limit,
            "single_position_limit_pct": single_pos_limit * 100,
            "max_leverage":         self._calculate_dynamic_leverage(total_portfolio_value),
            "kill_switch_active":   bool(kill_switch),
            "config":               config
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
    async def _check_tail_risk(self, symbol: str, current_price: Optional[float]) -> bool:
        """
        尾部风险对冲机制 (Anti-Black Swan):
        当资产 24h 内波动率或价格变动幅度剧烈，触发强制降仓/禁止新开仓。
        """
        if not current_price:
            return False
            
        # 实际实现应从数据库或行情接口获取最近 24h K 线。
        # 这里演示逻辑：假设 24h 波动阈值为 10%
        # 获取此 symbol 之前的记录（若存在）来计算。
        # 暂时用随机模拟触发，或根据 current_price 与 INITIAL_PRICE 对比
        # 在实际工程中，此函数应由 MarketAnalysisService 提供。
        
        # 演示逻辑：
        # 如果当前波动超过配置阈值（模拟：价格波动率 > 10%）
        import random
        # 模拟 5% 的概率发生“黑天鹅”波动，或根据价格变动幅度。
        return random.random() < 0.02 # 2% 的概率模拟黑天鹅或高波动拦截
        
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
