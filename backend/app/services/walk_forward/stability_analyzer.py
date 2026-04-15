import logging
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from app.services.backtester.annualization import infer_annualization_factor


logger = logging.getLogger(__name__)

class StabilityAnalyzer:
    """
    策略稳定性分析器
    提供 Walk-Forward Efficiency (WFE) 的计算与参数稳定性(Parameter Stability)评估
    """
    
    WFE_LOWER_BOUND = -2.0
    WFE_UPPER_BOUND = 2.0
    _WFE_DENOMINATOR_EPSILON = 1e-6

    @staticmethod
    def calculate_wfe(in_sample_returns: pd.Series, out_of_sample_returns: pd.Series, annualization_factor: int = 252) -> float:
        """
        计算单次或总体的 Walk-Forward Efficiency (WFE)
        WFE = 样本外年化收益率 / 样本内年化收益率
        
        :param in_sample_returns: 样本内收益率序列
        :param out_of_sample_returns: 样本外收益率序列
        :param annualization_factor: 年化因子 (例如日线数据为252)
        :return: WFE 值
        """
        is_returns = StabilityAnalyzer._coerce_returns(in_sample_returns)
        oos_returns = StabilityAnalyzer._coerce_returns(out_of_sample_returns)
        if is_returns.empty or oos_returns.empty:
            return 0.0

        StabilityAnalyzer._warn_if_returns_look_like_percentages(is_returns, "in_sample_returns")
        StabilityAnalyzer._warn_if_returns_look_like_percentages(oos_returns, "out_of_sample_returns")

        is_annualization_factor = StabilityAnalyzer._resolve_annualization_factor(is_returns.index, annualization_factor)
        oos_annualization_factor = StabilityAnalyzer._resolve_annualization_factor(oos_returns.index, annualization_factor)
        is_annualized_return = StabilityAnalyzer._annualized_return(is_returns, is_annualization_factor)
        oos_annualized_return = StabilityAnalyzer._annualized_return(oos_returns, oos_annualization_factor)

        # 仅在样本内收益接近0时跳过，保留真实负收益，避免掩盖 WFE 的方向性。
        if np.isclose(is_annualized_return, 0.0, atol=StabilityAnalyzer._WFE_DENOMINATOR_EPSILON):
            logger.warning(
                "WFE denominator is too close to zero; returning 0.0. "
                "is_annualized_return=%.6f, oos_annualized_return=%.6f, annualization_factor=%s",
                is_annualized_return,
                oos_annualized_return,
                is_annualization_factor,
            )
            return 0.0

        wfe = float(oos_annualized_return / is_annualized_return)
        if not np.isfinite(wfe):
            logger.warning(
                "Non-finite WFE detected; returning 0.0. "
                "is_annualized_return=%.6f, oos_annualized_return=%.6f",
                is_annualized_return,
                oos_annualized_return,
            )
            return 0.0

        if wfe < StabilityAnalyzer.WFE_LOWER_BOUND or wfe > StabilityAnalyzer.WFE_UPPER_BOUND:
            logger.warning(
                "WFE is outside the expected range [-200%%, 200%%]. "
                "wfe=%.6f, is_annualized_return=%.6f, oos_annualized_return=%.6f",
                wfe,
                is_annualized_return,
                oos_annualized_return,
            )

        return wfe

    @staticmethod
    def is_wfe_stable(wfe: float, threshold: float = 0.5) -> bool:
        """
        判断 WFE 是否满足稳定条件 (默认 > 50%)
        """
        return wfe > threshold

    @staticmethod
    def calculate_parameter_stability(optimal_params_list: List[Dict[str, float]]) -> Dict[str, float]:
        """
        计算最优参数在各个滚动窗口中的稳定性
        主要通过计算参数的变异系数 (Coefficient of Variation, CV = std / mean)
        稳定性分数 = max(0, 1 - CV)，接近1为稳定，接近0为不稳定。
        这里保留较强惩罚形式，以避免高漂移参数被高估。
        
        :param optimal_params_list: 每次Walk-Forward窗口产生的最优参数字典列表
        :return: 各参数的稳定性分数
        """
        if not optimal_params_list:
            return {}
            
        # 聚合每个参数的值
        param_values = {}
        for params in optimal_params_list:
            for k, v in params.items():
                if isinstance(v, (int, float)):
                    if k not in param_values:
                        param_values[k] = []
                    param_values[k].append(v)
                    
        stability_scores = {}
        for k, values in param_values.items():
            if len(values) < 2:
                stability_scores[k] = 1.0
                continue
                
            arr = np.array(values)
            mean_val = np.mean(arr)
            std_val = np.std(arr)
            
            if mean_val == 0:
                cv = std_val / 1e-6 if std_val != 0 else 0
            else:
                cv = abs(std_val / mean_val)
                
            # 改进稳定性分数计算公式，对高波动参数惩罚更大
            stability_scores[k] = max(0.0, 1.0 - cv)
            
        return stability_scores

    @staticmethod
    def calculate_window_parameter_stability(
        optimal_params_list: List[Dict[str, float]],
    ) -> List[float]:
        """
        计算逐窗口参数稳定度。

        返回长度与窗口数一致的列表：
        - 首个窗口默认记为 1.0
        - 后续窗口根据与前一窗口的参数漂移计算稳定度
        """
        if not optimal_params_list:
            return []

        window_scores: List[float] = [1.0]
        for idx in range(1, len(optimal_params_list)):
            previous_params = optimal_params_list[idx - 1]
            current_params = optimal_params_list[idx]
            shared_numeric_keys = [
                key
                for key in set(previous_params) & set(current_params)
                if isinstance(previous_params[key], (int, float)) and isinstance(current_params[key], (int, float))
            ]

            if not shared_numeric_keys:
                window_scores.append(1.0)
                continue

            per_param_scores: List[float] = []
            for key in shared_numeric_keys:
                previous_value = float(previous_params[key])
                current_value = float(current_params[key])
                scale = max(abs(previous_value), abs(current_value), 1.0)
                drift = abs(current_value - previous_value) / scale
                per_param_scores.append(max(0.0, 1.0 - drift))

            window_scores.append(float(np.mean(per_param_scores)) if per_param_scores else 1.0)

        return window_scores

    @staticmethod
    def analyze_wfo_results(wfo_results: List[Dict[str, Any]], annualization_factor: int = 252) -> Dict[str, Any]:
        """
        综合分析 Walk-Forward Optimization 结果
        
        :param wfo_results: WFO执行结果，每项应包含:
            - 'is_returns': 样本内收益序列 (pd.Series)
            - 'oos_returns': 样本外收益序列 (pd.Series)
            - 'optimal_params': 该窗口最优参数 (Dict)
        :param annualization_factor: 年化因子
        :return: 综合报告字典
        """
        all_wfe: List[float] = []
        optimal_params_list: List[Dict[str, float]] = []

        total_oos_returns_list: List[pd.Series] = []
        
        for res in wfo_results:
            is_rets = res.get('is_returns', pd.Series(dtype=float))
            oos_rets = res.get('oos_returns', pd.Series(dtype=float))
            params = res.get('optimal_params', {})
            
            wfe = StabilityAnalyzer.calculate_wfe(is_rets, oos_rets, annualization_factor)
            all_wfe.append(wfe)
            if params:
                optimal_params_list.append(params)
            
            if not oos_rets.empty:
                total_oos_returns_list.append(oos_rets)
                
        if total_oos_returns_list:
            total_oos_returns = pd.concat(total_oos_returns_list)
        else:
            total_oos_returns = pd.Series(dtype=float)
            
        avg_wfe = float(np.mean(all_wfe)) if all_wfe else 0.0
        param_stability = StabilityAnalyzer.calculate_parameter_stability(optimal_params_list)
        window_param_stability = StabilityAnalyzer.calculate_window_parameter_stability(optimal_params_list)
        
        return {
            'average_wfe': avg_wfe,
            'is_wfe_stable': StabilityAnalyzer.is_wfe_stable(avg_wfe),
            'wfe_per_window': all_wfe,
            'parameter_stability_scores': param_stability,
            'window_parameter_stability': window_param_stability,
            'total_oos_annualized_return': (
                StabilityAnalyzer._annualized_return(
                    total_oos_returns,
                    StabilityAnalyzer._resolve_annualization_factor(total_oos_returns.index, annualization_factor),
                )
                if not total_oos_returns.empty else 0.0
            ),
            'metric_types': {
                'average_wfe': 'decimal',
                'wfe_per_window': 'decimal',
                'parameter_stability_scores': 'decimal',
                'window_parameter_stability': 'decimal',
                'total_oos_annualized_return': 'decimal',
            },
        }

    @staticmethod
    def _annualized_return(returns: pd.Series, annualization_factor: int) -> float:
        """
        内部方法：按小数口径计算年化收益率。

        例如返回 `0.12` 表示 12%，展示层需要自行乘以100。
        """
        sanitized_returns = StabilityAnalyzer._coerce_returns(returns)
        if sanitized_returns.empty or annualization_factor <= 0:
            return 0.0

        # 收益率序列必须使用小数口径，例如 1% 应传入 0.01 而不是 1.0。
        cum_return = (1 + sanitized_returns).prod() - 1
        n_periods = len(sanitized_returns)

        if cum_return <= -1.0:
            return -1.0

        return float((1 + cum_return) ** (annualization_factor / n_periods) - 1)

    @staticmethod
    def _coerce_returns(returns: pd.Series) -> pd.Series:
        """清洗收益率序列，统一为 float 并移除缺失值。"""
        return pd.Series(returns, dtype=float).dropna()

    @staticmethod
    def _warn_if_returns_look_like_percentages(returns: pd.Series, series_name: str) -> None:
        """
        WFA 内部统一使用小数收益率；若检测到超过 ±100% 的单期收益，提示可能混入了百分数口径。
        """
        if returns.empty:
            return

        large_returns = returns.abs() > 1.0
        if not large_returns.any():
            return

        logger.warning(
            "%s contains values outside [-1, 1]. WFA expects decimal returns, not percentage points. "
            "offending_points=%s/%s, max_abs_return=%.6f",
            series_name,
            int(large_returns.sum()),
            len(returns),
            float(returns.abs().max()),
        )

    @staticmethod
    def _resolve_annualization_factor(index: pd.Index, fallback_annualization_factor: int) -> int:
        """优先使用当前窗口索引推导年化因子，失败时回退到调用方传入的默认值。"""
        if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
            try:
                return max(infer_annualization_factor(index), 1)
            except ValueError:
                logger.warning(
                    "Failed to infer annualization factor from returns index; using fallback=%s.",
                    fallback_annualization_factor,
                )

        return max(fallback_annualization_factor, 1)
