"""
VectorizedBacktester 信号修复的针对性单元测试

测试目标：验证修复后的向量化回测引擎能正确处理稀疏动作信号，
将其转换为连续持仓状态，确保与 EventDrivenBacktester 行为一致。

修复要点：
- 修复前：将稀疏动作信号（仅交叉当天为1/-1，其余为0）直接当作持仓状态
- 修复后：使用 replace(0, np.nan).ffill().fillna(0).clip(lower=0) 将动作信号转换为连续持仓状态
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from app.services.backtester.vectorized import VectorizedBacktester
from app.services.backtester.event_driven import EventDrivenBacktester


def create_test_data(days: int, start_price: float = 100.0) -> pd.DataFrame:
    """创建测试用的价格数据"""
    dates = pd.date_range(start='2024-01-01', periods=days, freq='D')
    
    # 构造简单的价格序列：每天上涨1%
    prices = [start_price * (1.01 ** i) for i in range(days)]
    
    df = pd.DataFrame({
        'open': prices,
        'high': [p * 1.02 for p in prices],
        'low': [p * 0.98 for p in prices],
        'close': prices,
        'volume': [1000.0] * days
    }, index=dates)
    
    return df


def create_constant_price_data(days: int, price: float = 100.0) -> pd.DataFrame:
    """创建价格恒定的测试数据（用于手续费测试）"""
    dates = pd.date_range(start='2024-01-01', periods=days, freq='D')
    
    df = pd.DataFrame({
        'open': [price] * days,
        'high': [price * 1.01] * days,
        'low': [price * 0.99] * days,
        'close': [price] * days,
        'volume': [1000.0] * days
    }, index=dates)
    
    return df


class TestContinuousPositionHolding:
    """测试持续持仓：金叉到死叉期间应持续持仓"""
    
    def test_持续持仓_金叉到死叉(self):
        """
        构造信号序列：[0, 0, 1, 0, 0, 0, -1, 0, 0]
        验证修复后 pos 在买入后持续为1，直到卖出信号后变为0
        验证中间日期（信号为0）不会导致平仓
        """
        # 9天的数据
        df = create_test_data(9)
        
        # 信号序列：第3天买入(1)，第7天卖出(-1)
        signal_values = [0, 0, 1, 0, 0, 0, -1, 0, 0]
        
        def signal_func(df):
            return pd.Series(signal_values, index=df.index)
        
        backtester = VectorizedBacktester(df, signal_func, initial_capital=10000.0, commission=0.001)
        result = backtester.run()
        
        # 验证：最终应该有收益（因为持仓期间价格上涨）
        assert result['total_return'] > 0, "持仓期间价格上涨，应有正收益"
        
        # 验证：应该有2次交易（开仓+平仓）
        assert result['total_trades'] == 2, f"应该有2次交易（开仓+平仓），实际为{result['total_trades']}"
        
        # 验证：最终资本应大于初始资本
        assert result['final_capital'] > 10000.0, "持仓期间价格上涨，最终资本应增加"
    
    def test_单日信号不提前平仓(self):
        """
        构造一个只有买入信号没有卖出信号的序列
        验证买入后一直持仓到序列结束
        
        注意：VectorizedBacktester 不会在最后一天强制平仓，
        它只会在有明确的卖出信号(-1)时才平仓。
        """
        # 10天的数据
        df = create_test_data(10)
        
        # 信号序列：第3天买入(1)，之后无卖出信号
        signal_values = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
        
        def signal_func(df):
            return pd.Series(signal_values, index=df.index)
        
        backtester = VectorizedBacktester(df, signal_func, initial_capital=10000.0, commission=0.001)
        result = backtester.run()
        
        # 验证：最终应该有收益（因为持仓到结束，价格一直在涨）
        assert result['total_return'] > 0, "买入后持仓到结束，应有正收益"
        
        # 验证：应该只有1次交易（仅开仓，因为没有卖出信号）
        # VectorizedBacktester 不会在最后一天强制平仓
        # pos = position.shift(1).fillna(0)
        # trades = pos.diff().abs()，只有开仓时pos从0变1产生一次变化
        assert result['total_trades'] == 1, f"应该有1次交易（仅开仓），实际为{result['total_trades']}"


class TestCommissionCorrectness:
    """测试手续费计算正确性"""
    
    def test_手续费正确性(self):
        """
        构造含一次完整开平仓的信号
        验证手续费仅在开仓和平仓时各扣一次（共2次），而非每天扣
        """
        # 使用恒定价格数据，这样收益完全来自手续费计算
        df = create_constant_price_data(10, price=100.0)
        
        # 信号序列：第3天买入，第7天卖出
        signal_values = [0, 0, 1, 0, 0, 0, -1, 0, 0, 0]
        
        def signal_func(df):
            return pd.Series(signal_values, index=df.index)
        
        commission_rate = 0.001
        initial_capital = 10000.0
        
        backtester = VectorizedBacktester(df, signal_func, initial_capital=initial_capital, commission=commission_rate)
        result = backtester.run()
        
        # 计算预期手续费：开仓一次 + 平仓一次 = 2次
        # 每次手续费 = 交易金额 * 手续费率
        # 开仓：10000 * 0.001 = 10
        # 平仓：10000 * 0.001 = 10
        # 总手续费 = 20
        expected_commission = initial_capital * commission_rate * 2  # 开仓+平仓
        
        # 由于价格不变，收益应该完全等于 -手续费
        expected_final = initial_capital - expected_commission
        
        # 允许小的浮点误差
        assert abs(result['final_capital'] - expected_final) < 1.0, \
            f"最终资本应为 {expected_final}（扣除手续费），实际为 {result['final_capital']}"


class TestEngineConsistency:
    """测试 VectorizedBacktester 与 EventDrivenBacktester 一致性"""
    
    def test_与EventDriven引擎一致性(self):
        """
        使用相同的价格数据和信号序列
        分别用 VectorizedBacktester 和 EventDrivenBacktester 运行
        验证最终收益（total_return）在合理误差范围内一致（允许1%以内浮点误差）
        """
        # 创建测试数据
        df = create_test_data(20)
        
        # 构造一个更复杂的信号序列：包含多次买卖
        signal_values = [0, 0, 1, 0, 0, -1, 0, 0, 1, 0, 0, 0, -1, 0, 0, 1, 0, -1, 0, 0]
        
        def signal_func(df):
            return pd.Series(signal_values, index=df.index)
        
        initial_capital = 10000.0
        commission = 0.001
        
        # 运行向量化回测
        vec_backtester = VectorizedBacktester(df, signal_func, initial_capital=initial_capital, commission=commission)
        vec_result = vec_backtester.run()
        
        # 运行事件驱动回测
        evt_backtester = EventDrivenBacktester(df, signal_func, initial_capital=initial_capital, commission=commission)
        evt_result = evt_backtester.run()
        
        # 验证总收益在1%误差范围内一致
        vec_return = vec_result['total_return']
        evt_return = evt_result['total_return']
        
        return_diff_pct = abs(vec_return - evt_return) / abs(evt_return) * 100 if evt_return != 0 else abs(vec_return - evt_return)
        
        assert return_diff_pct < 1.0, \
            f"两个引擎的总收益差异超过1%：Vectorized={vec_return:.4f}%, EventDriven={evt_return:.4f}%, 差异={return_diff_pct:.4f}%"
        
        # 验证交易次数一致
        assert vec_result['total_trades'] == evt_result['total_trades'] * 2, \
            f"交易次数不一致：Vectorized={vec_result['total_trades']}, EventDriven={evt_result['total_trades'] * 2}"


class TestEdgeCases:
    """测试边界条件"""
    
    def test_边界条件_全零信号(self):
        """
        全0信号应产生0收益（不考虑手续费，因为没有交易）
        """
        df = create_test_data(10)
        
        # 全0信号
        signal_values = [0] * 10
        
        def signal_func(df):
            return pd.Series(signal_values, index=df.index)
        
        backtester = VectorizedBacktester(df, signal_func, initial_capital=10000.0, commission=0.001)
        result = backtester.run()
        
        # 全0信号意味着没有持仓，收益应为0
        assert abs(result['total_return']) < 0.01, \
            f"全0信号应产生0收益，实际为 {result['total_return']}%"
        
        # 没有交易
        assert result['total_trades'] == 0, \
            f"全0信号应无交易，实际交易次数为 {result['total_trades']}"
        
        # 最终资本应等于初始资本
        assert abs(result['final_capital'] - 10000.0) < 0.01, \
            f"全0信号最终资本应等于初始资本，实际为 {result['final_capital']}"

    def test_边界条件_OOS继承持仓后零信号不应幽灵平仓(self):
        df = create_constant_price_data(6, price=100.0)

        def signal_func(df):
            return pd.Series([0, 0, 0, 0, 0, 0], index=df.index)

        backtester = VectorizedBacktester(
            df,
            signal_func,
            initial_capital=10000.0,
            commission=0.001,
            initial_position=1.0,
        )
        result = backtester.run()

        assert result["total_trades"] == 0, f"OOS开头全零信号不应触发虚假平仓，实际交易次数为 {result['total_trades']}"
        assert result["final_position"] == 1.0, f"OOS末尾应继续保持上一窗口仓位，实际为 {result['final_position']}"
        assert abs(result["final_capital"] - 10000.0) < 0.01, \
            f"常数价格且无真实交易时资本不应变化，实际为 {result['final_capital']}"

    def test_边界条件_最后一根买入信号应传递到下一窗口(self):
        df = create_constant_price_data(5, price=100.0)

        def signal_func(df):
            return pd.Series([0, 0, 0, 0, 1], index=df.index)

        backtester = VectorizedBacktester(
            df,
            signal_func,
            initial_capital=10000.0,
            commission=0.001,
            initial_position=0.0,
        )
        result = backtester.run()

        assert result["total_trades"] == 0, f"最后一根信号应在下一根K线才成交，当前窗口不应有交易，实际为 {result['total_trades']}"
        assert result["final_position"] == 1.0, f"最后一根买入信号应作为下一窗口继承仓位，实际为 {result['final_position']}"
    
    def test_边界条件_首日买入信号(self):
        """
        第一天就有买入信号的情况
        由于shift(1)，第一天信号会被移到第二天才生效
        """
        df = create_test_data(10)
        
        # 首日买入信号
        signal_values = [1, 0, 0, 0, 0, -1, 0, 0, 0, 0]
        
        def signal_func(df):
            return pd.Series(signal_values, index=df.index)
        
        backtester = VectorizedBacktester(df, signal_func, initial_capital=10000.0, commission=0.001)
        result = backtester.run()
        
        # 应该有交易发生
        assert result['total_trades'] >= 2, \
            f"首日买入信号应有交易发生，实际交易次数为 {result['total_trades']}"
        
        # 由于持仓期间价格上涨，应有正收益
        assert result['total_return'] > 0, "持仓期间价格上涨，应有正收益"
    
    def test_连续买入信号(self):
        """
        多个连续的1信号，应只在第一个1时开仓，后续的1不应重复开仓
        """
        df = create_test_data(10)
        
        # 连续买入信号，然后卖出
        signal_values = [0, 1, 1, 1, 0, 0, -1, 0, 0, 0]
        
        def signal_func(df):
            return pd.Series(signal_values, index=df.index)
        
        backtester = VectorizedBacktester(df, signal_func, initial_capital=10000.0, commission=0.001)
        result = backtester.run()
        
        # 应该只有2次交易（开仓+平仓），而不是多次开仓
        assert result['total_trades'] == 2, \
            f"连续买入信号应只开仓一次，总交易次数应为2，实际为 {result['total_trades']}"


class TestSignalConversion:
    """测试信号转换逻辑的内部正确性"""
    
    def test_信号转换_ffill逻辑(self):
        """
        直接测试信号转换的核心逻辑：
        replace(0, np.nan).ffill().fillna(0).clip(lower=0)
        """
        # 原始信号
        signals = pd.Series([0, 0, 1, 0, 0, 0, -1, 0, 0])
        
        # 应用转换逻辑（复制自vectorized.py）
        position = signals.replace(0, np.nan).ffill().fillna(0)
        position = position.clip(lower=0)
        
        # 预期结果：[0, 0, 1, 1, 1, 1, 0, 0, 0]
        expected = pd.Series([0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
        
        pd.testing.assert_series_equal(position, expected, check_names=False)
    
    def test_信号转换_带shift(self):
        """
        测试包含shift(1)的完整信号转换，避免未来函数偏差
        """
        # 原始信号
        signals = pd.Series([0, 0, 1, 0, 0, 0, -1, 0, 0])
        
        # 应用完整转换逻辑
        position = signals.replace(0, np.nan).ffill().fillna(0)
        position = position.clip(lower=0)
        pos = position.shift(1).fillna(0)
        
        # 预期结果（shift后）：[0, 0, 0, 1, 1, 1, 1, 0, 0]
        expected = pd.Series([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0])
        
        pd.testing.assert_series_equal(pos, expected, check_names=False)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
