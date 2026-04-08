import numpy as np
import pandas as pd
from typing import List, Dict, Any

class StabilityAnalyzer:
    """
    策略稳定性分析器
    提供 Walk-Forward Efficiency (WFE) 的计算与参数稳定性(Parameter Stability)评估
    """
    
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
        if in_sample_returns.empty or out_of_sample_returns.empty:
            return 0.0
            
        is_annualized_return = StabilityAnalyzer._annualized_return(in_sample_returns, annualization_factor)
        oos_annualized_return = StabilityAnalyzer._annualized_return(out_of_sample_returns, annualization_factor)
        
        # 避免除以0或极小值，如果样本内收益为负，说明优化结果也是亏损的，效率记为0
        if is_annualized_return <= 1e-6:
            return 0.0
            
        wfe = oos_annualized_return / is_annualized_return
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
        稳定性分数 = 1 / (1 + CV)，接近1为稳定，接近0为不稳定
        
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
        all_wfe = []
        optimal_params_list = []
        
        total_oos_returns_list = []
        
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
        
        return {
            'average_wfe': avg_wfe,
            'is_wfe_stable': StabilityAnalyzer.is_wfe_stable(avg_wfe),
            'wfe_per_window': all_wfe,
            'parameter_stability_scores': param_stability,
            'total_oos_annualized_return': StabilityAnalyzer._annualized_return(total_oos_returns, annualization_factor) if not total_oos_returns.empty else 0.0
        }

    @staticmethod
    def _annualized_return(returns: pd.Series, annualization_factor: int) -> float:
        """内部方法：计算年化收益率（简单复利）"""
        if len(returns) == 0:
            return 0.0
        
        # 将收益率转换为+1后的乘积
        cum_return = (1 + returns).prod() - 1
        n_periods = len(returns)
        
        if cum_return <= -1.0:
            return -1.0
            
        return float((1 + cum_return) ** (annualization_factor / n_periods) - 1)
