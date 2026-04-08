import pandas as pd
from typing import List, Dict, Union, Tuple
from datetime import timedelta

class WindowManager:
    """
    Walk-Forward Optimization (WFO) 窗口管理器
    支持滚动窗口(Rolling)和扩展窗口(Expanding)
    支持数据泄露隔离期(Embargo)
    """
    def __init__(self, 
                 method: str = 'rolling', 
                 train_size: Union[int, pd.Timedelta, timedelta] = 252, 
                 test_size: Union[int, pd.Timedelta, timedelta] = 63,
                 step_size: Union[int, pd.Timedelta, timedelta] = None,
                 embargo_size: Union[int, pd.Timedelta, timedelta] = 0):
        """
        初始化窗口管理器
        
        :param method: 窗口移动方式，'rolling' 或 'expanding'
        :param train_size: 训练集大小（整数表示周期数，Timedelta表示时间跨度）
        :param test_size: 测试集大小
        :param step_size: 步长，默认为测试集大小
        :param embargo_size: 训练集和测试集之间的隔离期大小，防止未来数据泄露
        """
        if method not in ['rolling', 'expanding']:
            raise ValueError("method must be 'rolling' or 'expanding'")
            
        self.method = method
        self.train_size = train_size
        self.test_size = test_size
        self.step_size = step_size if step_size is not None else test_size
        self.embargo_size = embargo_size

    def generate_windows(self, data_index: pd.DatetimeIndex) -> List[Dict[str, Tuple[pd.Timestamp, pd.Timestamp]]]:
        """
        生成 Walk-Forward 时间窗口
        
        :param data_index: 数据的时间索引，必须单调递增
        :return: 包含 train 和 test 时间元组的字典列表，每个元组格式为 (start_time, end_time)
        """
        if not isinstance(data_index, pd.DatetimeIndex):
            data_index = pd.DatetimeIndex(data_index)
            
        if not data_index.is_monotonic_increasing:
            data_index = data_index.sort_values()

        if isinstance(self.train_size, int):
            return self._generate_index_windows(data_index)
        elif isinstance(self.train_size, (timedelta, pd.Timedelta)):
            return self._generate_time_windows(data_index)
        else:
            raise TypeError("Size parameters must be int or timedelta/pd.Timedelta")

    def _generate_index_windows(self, data_index: pd.DatetimeIndex) -> List[Dict[str, Tuple[pd.Timestamp, pd.Timestamp]]]:
        windows = []
        n_samples = len(data_index)
        
        train_size = int(self.train_size)
        test_size = int(self.test_size)
        step_size = int(self.step_size)
        embargo_size = int(self.embargo_size)
        
        start_idx = 0
        
        while True:
            train_end_idx = start_idx + train_size
            test_start_idx = train_end_idx + embargo_size
            test_end_idx = test_start_idx + test_size
            
            if test_end_idx > n_samples:
                break
                
            train_start = data_index[0] if self.method == 'expanding' else data_index[start_idx]
            train_end = data_index[train_end_idx - 1]
            test_start = data_index[test_start_idx]
            test_end = data_index[test_end_idx - 1]
            
            windows.append({
                'train': (train_start, train_end),
                'test': (test_start, test_end)
            })
            
            start_idx += step_size
            
        return windows

    def _generate_time_windows(self, data_index: pd.DatetimeIndex) -> List[Dict[str, Tuple[pd.Timestamp, pd.Timestamp]]]:
        windows = []
        
        start_time = data_index[0]
        end_time = data_index[-1]
        
        current_train_start = start_time
        
        train_td = pd.Timedelta(self.train_size)
        test_td = pd.Timedelta(self.test_size)
        step_td = pd.Timedelta(self.step_size)
        embargo_td = pd.Timedelta(self.embargo_size)
        
        while True:
            train_end = current_train_start + train_td
            test_start = train_end + embargo_td
            test_end = test_start + test_td
            
            if test_end > end_time:
                break
                
            train_start = start_time if self.method == 'expanding' else current_train_start
            
            # 找到对应时间的实际数据点边界
            # 训练集：[train_start, train_end) 
            # 测试集：[test_start, test_end)
            train_mask = (data_index >= train_start) & (data_index < train_end)
            test_mask = (data_index >= test_start) & (data_index < test_end)
            
            if train_mask.any() and test_mask.any():
                actual_train_start = data_index[train_mask][0]
                actual_train_end = data_index[train_mask][-1]
                actual_test_start = data_index[test_mask][0]
                actual_test_end = data_index[test_mask][-1]
                
                windows.append({
                    'train': (actual_train_start, actual_train_end),
                    'test': (actual_test_start, actual_test_end)
                })
            
            current_train_start += step_td
            
        return windows
