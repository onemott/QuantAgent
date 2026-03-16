"""
Transaction Cost Analysis (TCA) Service
Analyzes trading performance, slippage, and costs.
"""

import logging
import pandas as pd
import numpy as np
from sqlalchemy import select
from app.services.database import get_db
from app.models.db_models import PaperTrade
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TCAService:
    async def generate_report(self, symbol: str = None) -> Dict[str, Any]:
        """
        Generate TCA report for a specific symbol or all symbols.
        Includes Implementation Shortfall, Funding Drag, and Slippage Analysis.
        """
        async with get_db() as session:
            stmt = select(PaperTrade).order_by(PaperTrade.created_at)
            if symbol:
                stmt = stmt.where(PaperTrade.symbol == symbol)
            result = await session.execute(stmt)
            trades = result.scalars().all()
            
        if not trades:
            return {"message": "No trades found"}
            
        # Convert to DataFrame
        data = []
        for t in trades:
            data.append({
                "symbol": t.symbol,
                "side": t.side,
                "qty": float(t.quantity),
                "price": float(t.price),
                "benchmark_price": float(t.benchmark_price) if t.benchmark_price else float(t.price),
                "fee": float(t.fee),
                "funding_fee": float(t.funding_fee) if t.funding_fee else 0.0,
                "pnl": float(t.pnl) if t.pnl is not None else 0.0,
                "status": t.status,
                "timestamp": t.created_at
            })
            
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Filter only filled orders for cost analysis
        filled_df = df[df['status'] == 'FILLED'].copy()
        
        if filled_df.empty:
             return {"message": "No filled trades found"}

        # 1. Total Costs
        total_fees = filled_df['fee'].sum()
        total_funding = filled_df['funding_fee'].sum()
        total_pnl = filled_df['pnl'].sum()
        total_volume = (filled_df['qty'] * filled_df['price']).sum()
        
        # 2. Implementation Shortfall (IS)
        # IS = Side * (Execution Price - Benchmark Price) * Quantity
        # Side: Buy=1, Sell=-1
        # Note: PaperTrade 'side' is direction.
        filled_df['side_sign'] = filled_df['side'].apply(lambda x: 1 if x == 'BUY' else -1)
        filled_df['is_abs'] = filled_df['side_sign'] * (filled_df['price'] - filled_df['benchmark_price']) * filled_df['qty']
        filled_df['is_bps'] = (filled_df['is_abs'] / (filled_df['benchmark_price'] * filled_df['qty'])) * 10000
        
        total_shortfall = filled_df['is_abs'].sum()
        avg_shortfall_bps = filled_df['is_bps'].mean()
        
        # 3. Win/Loss Metrics (Based on Realized PnL)
        # Filter trades that have realized PnL (usually closing trades)
        closed_trades = filled_df[filled_df['pnl'] != 0]
        win_trades = closed_trades[closed_trades['pnl'] > 0]
        loss_trades = closed_trades[closed_trades['pnl'] < 0]
        
        win_rate = len(win_trades) / len(closed_trades) if len(closed_trades) > 0 else 0
        avg_win = win_trades['pnl'].mean() if not win_trades.empty else 0
        avg_loss = abs(loss_trades['pnl'].mean()) if not loss_trades.empty else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        
        # 4. VWAP
        vwap = (filled_df['qty'] * filled_df['price']).sum() / filled_df['qty'].sum() if filled_df['qty'].sum() > 0 else 0
        
        return {
            "symbol": symbol or "ALL",
            "total_trades": len(filled_df),
            "total_volume_usdt": round(total_volume, 2),
            "total_fees_usdt": round(total_fees, 2),
            "total_funding_usdt": round(total_funding, 2),
            "net_pnl_usdt": round(total_pnl, 2),
            "implementation_shortfall_usdt": round(total_shortfall, 4),
            "avg_shortfall_bps": round(avg_shortfall_bps, 2),
            "win_rate_pct": round(win_rate * 100, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "vwap": round(vwap, 4)
        }

# Singleton
tca_service = TCAService()
