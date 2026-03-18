# QAD (Quant Attribution & Dissection) 差异归因框架 SPEC 文档
**文档版本**：v1.0  
**编写日期**：2026-03-17  
**目标**：基于订单级对齐实现回测与模拟盘的收益差异分解，输出可解释的归因结果及可视化图表。


## 1. 项目概述
### 1.1 项目背景
量化策略开发中，回测与模拟盘的收益差异缺乏透明归因，无法定位“回测漂亮、实盘亏损”的核心原因。本框架通过微观订单对齐，将差异分解为价格、成交率、手续费等可解释维度。

### 1.2 核心目标
- **订单级对齐**：以唯一信号ID为桥梁，匹配回测与模拟盘的同源交易；
- **多维度分解**：将总收益差拆分为价格、成交率、时机、手续费4个互斥维度；
- **可视化输出**：生成瀑布图、时间序列堆积图、散点图，支撑业务决策。

### 1.3 范围
- 支持股票、期货等品种的日线/Tick级归因；
- 时机差异为可选功能（高频策略启用，中低频可忽略）；
- 输出格式：Pandas DataFrame + Plotly 图表。


## 2. 功能需求
| 功能模块   | 需求描述                                                                                                                 | 验收标准                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------- |
| 数据预处理 | 1. 支持多笔成交聚合（1个信号对应多笔成交时，按成交量加权平均价格、求和手续费）；<br>2. 自动对齐回测/模拟盘成交表与信号表 | 聚合后1个signal_id仅对应1行成交记录 |
| 差异分解   | 1. 计算价格差异、成交率差异、手续费差异；<br>2. 可选计算时机差异（需接入基准行情表）；<br>3. 校验总差异=各分项差异之和   | 人工构造测试用例，计算误差<0.01元   |
| 结果聚合   | 1. 按日聚合差异；<br>2. 按品种聚合差异；<br>3. 全局聚合总差异                                                            | 聚合结果与微观订单计算总和一致      |
| 可视化     | 1. 生成总体归因瀑布图；<br>2. 生成每日差异时间序列堆积图；<br>3. 生成价格差异散点图                                      | 图表支持交互（缩放、悬停显示详情）  |


## 3. 数据模型
### 3.1 输入数据表
#### 表1：信号表 (`df_signals`)
| 字段名          | 类型     | 必填 | 说明                        | 示例                |
| --------------- | -------- | ---- | --------------------------- | ------------------- |
| `signal_id`     | str      | 是   | 唯一信号ID（核心对齐键）    | "SIG_20260317_001"  |
| `timestamp`     | datetime | 是   | 信号生成时间                | 2026-03-17 09:35:00 |
| `symbol`        | str      | 是   | 品种代码                    | "600519.SH"         |
| `direction`     | int      | 是   | 交易方向（1=买入，-1=卖出） | 1                   |
| `target_qty`    | float    | 是   | 目标交易数量                | 100                 |
| `trigger_price` | float    | 是   | 信号触发时的基准价格        | 1800.00             |

#### 表2：回测成交表 (`df_bt_exec`)
| 字段名       | 类型     | 必填 | 说明           | 示例                |
| ------------ | -------- | ---- | -------------- | ------------------- |
| `signal_id`  | str      | 是   | 关联的信号ID   | "SIG_20260317_001"  |
| `exec_id`    | str      | 是   | 成交唯一ID     | "BT_EXEC_001"       |
| `exec_ts`    | datetime | 是   | 成交时间       | 2026-03-17 09:35:01 |
| `exec_price` | float    | 是   | 成交价格       | 1800.00             |
| `exec_qty`   | float    | 是   | 成交数量       | 100                 |
| `fee`        | float    | 是   | 手续费（正数） | 5.00                |

#### 表3：模拟盘成交表 (`df_sim_exec`)
*结构与 `df_bt_exec` 完全一致*

#### 表4：基准行情表 (`df_mkt`)（可选，仅时机差异需要）
| 字段名      | 类型     | 必填 | 说明                      | 示例                |
| ----------- | -------- | ---- | ------------------------- | ------------------- |
| `timestamp` | datetime | 是   | 行情时间戳                | 2026-03-17 09:35:01 |
| `symbol`    | str      | 是   | 品种代码                  | "600519.SH"         |
| `mid_price` | float    | 是   | 市场中间价（买一+卖一）/2 | 1800.20             |


### 3.2 中间输出表
#### 表5：合并宽表 (`df_combined`)
| 字段名          | 类型     | 说明                                     |
| --------------- | -------- | ---------------------------------------- |
| `signal_id`     | str      | 信号ID                                   |
| `timestamp`     | datetime | 信号生成时间                             |
| `symbol`        | str      | 品种代码                                 |
| `direction`     | int      | 交易方向                                 |
| `trigger_price` | float    | 信号触发价格                             |
| `bt_price`      | float    | 回测加权平均成交价                       |
| `bt_qty`        | float    | 回测总成交数量                           |
| `bt_fee`        | float    | 回测总手续费                             |
| `sim_price`     | float    | 模拟盘加权平均成交价                     |
| `sim_qty`       | float    | 模拟盘总成交数量                         |
| `sim_fee`       | float    | 模拟盘总手续费                           |
| `sim_exec_ts`   | datetime | 模拟盘最后一笔成交时间（仅时机差异需要） |


### 3.3 最终结果表
#### 表6：归因结果表 (`df_attribution`)
在 `df_combined` 基础上新增以下字段：
| 字段名         | 类型  | 说明                                                 |
| -------------- | ----- | ---------------------------------------------------- |
| `q_common`     | float | 回测与模拟盘的共同成交数量                           |
| `q_diff`       | float | 模拟盘与回测的成交数量差（sim_qty - bt_qty）         |
| `delta_price`  | float | 价格差异（正数=模拟盘优于回测，负数=模拟盘差于回测） |
| `delta_fill`   | float | 成交率差异                                           |
| `delta_timing` | float | 时机差异（可选，无则为0）                            |
| `delta_fees`   | float | 手续费差异                                           |
| `delta_total`  | float | 总差异（校验用）                                     |


## 4. 算法设计
### 4.1 步骤1：多笔成交聚合
**目标**：若1个信号对应多笔成交，需聚合为1行记录。  
**逻辑**：
- `exec_qty`：求和；
- `exec_price`：按成交量加权平均（`sum(exec_price * exec_qty) / sum(exec_qty)`）；
- `fee`：求和；
- `exec_ts`：取最后一笔成交时间（仅模拟盘需要，用于时机差异）。

**示例代码逻辑**：
```python
def aggregate_executions(df_exec):
    agg_dict = {
        'exec_qty': 'sum',
        'exec_price': lambda x: np.average(x, weights=df_exec.loc[x.index, 'exec_qty']),
        'fee': 'sum',
        'exec_ts': 'max'  # 仅模拟盘需要
    }
    return df_exec.groupby('signal_id').agg(agg_dict).reset_index()
```


### 4.2 步骤2：数据合并与宽表生成
**目标**：将信号表与聚合后的回测/模拟盘成交表合并为宽表。  
**逻辑**：
1.  聚合回测成交表，重命名字段：`exec_price`→`bt_price`，`exec_qty`→`bt_qty`，`fee`→`bt_fee`；
2.  聚合模拟盘成交表，重命名字段：`exec_price`→`sim_price`，`exec_qty`→`sim_qty`，`fee`→`sim_fee`，`exec_ts`→`sim_exec_ts`；
3.  以 `df_signals` 为主表，Left Join 聚合后的回测表（on `signal_id`）；
4.  再 Left Join 聚合后的模拟盘表（on `signal_id`）；
5.  缺失值填充：`bt_price`/`bt_qty`/`bt_fee` 无成交填0；`sim_price`/`sim_qty`/`sim_fee` 无成交填0。


### 4.3 步骤3：微观差异分解
#### 3.1 共同成交量与数量差
$$
Q_{common} = \min(bt\_qty, sim\_qty)
$$
$$
Q_{diff} = sim\_qty - bt\_qty
$$

#### 3.2 价格差异 ($\Delta_{Price}$)
**定义**：共同成交部分因价格不同导致的收益差。  
**公式**：
$$
\Delta_{Price} = (sim\_price - bt\_price) \times Q_{common} \times direction
$$
**逻辑**：仅当 $Q_{common} > 0$ 时计算，否则为0。

#### 3.3 成交率差异 ($\Delta_{Fill}$)
**定义**：因成交数量不同导致的收益差（以回测价格为基准）。  
**公式**：
$$
\Delta_{Fill} = Q_{diff} \times bt\_price \times direction
$$

#### 3.4 时机差异 ($\Delta_{Timing}$)（可选）
**定义**：因成交时间延迟导致的价格漂移收益差（需基准行情表）。  
**逻辑**：
1.  对每个信号，找到 `sim_exec_ts` 前后最近的 `df_mkt.mid_price`（若时间完全匹配则直接取，否则用线性插值）；
2.  计算：
$$
\Delta_{Timing} = (mid\_price - bt\_price) \times Q_{common} \times direction
$$
*注：中低频策略可跳过此项，默认填0。*

#### 3.5 手续费差异 ($\Delta_{Fees}$)
**定义**：回测与模拟盘的手续费成本差。  
**公式**：
$$
\Delta_{Fees} = bt\_fee - sim\_fee
$$
*注：手续费是成本，因此回测手续费更高时，模拟盘相对收益更高（差异为正）。*

#### 3.6 总差异校验
$$
\Delta_{Total} = \Delta_{Price} + \Delta_{Fill} + \Delta_{Timing} + \Delta_{Fees}
$$
*校验标准：所有信号的 $\Delta_{Total}$ 之和应等于（模拟盘总收益 - 回测总收益），误差<0.01元。*


### 4.4 步骤4：结果聚合
**逻辑**：
- 按日聚合：提取 `timestamp` 的日期部分，分组求和各差异项；
- 按品种聚合：按 `symbol` 分组求和各差异项；
- 全局聚合：直接求和所有信号的各差异项。


## 5. 接口设计
### 5.1 核心函数签名
```python
import pandas as pd
import numpy as np
from typing import Optional, Tuple

def aggregate_executions(df_exec: pd.DataFrame) -> pd.DataFrame:
    """
    聚合成交表：1个信号对应多笔成交时，合并为1行
    输入：原始成交表（df_bt_exec 或 df_sim_exec）
    输出：聚合后的成交表，字段重命名为 {bt/sim}_price, {bt/sim}_qty, {bt/sim}_fee, sim_exec_ts（仅模拟盘）
    """
    pass

def merge_data(
    df_signals: pd.DataFrame,
    df_bt_agg: pd.DataFrame,
    df_sim_agg: pd.DataFrame
) -> pd.DataFrame:
    """
    合并信号表与聚合后的回测/模拟盘表，生成宽表
    输入：信号表、聚合后的回测表、聚合后的模拟盘表
    输出：df_combined（含缺失值填充）
    """
    pass

def calculate_attribution(
    df_combined: pd.DataFrame,
    df_mkt: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    核心归因计算函数
    输入：合并宽表 df_combined，基准行情表 df_mkt（可选）
    输出：df_attribution（含所有差异分解字段）
    """
    pass

def aggregate_results(df_attribution: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    结果聚合函数
    输入：归因结果表 df_attribution
    输出：(df_daily_agg, df_symbol_agg, df_global_agg)
    """
    pass
```


## 6. 可视化需求
### 6.1 总体归因瀑布图
**工具**：Plotly  
**输入数据**：`df_global_agg`  
**展示内容**：
- 起点：回测总收益（需额外计算：`sum((bt_price - trigger_price) * bt_qty * direction - bt_fee)`）；
- 中间项：`delta_price`、`delta_fill`、`delta_timing`、`delta_fees`；
- 终点：模拟盘总收益（回测收益 + 总差异）。  
**要求**：
- 正数用绿色，负数用红色；
- 悬停显示具体金额及占比。


### 6.2 每日差异时间序列堆积图
**工具**：Plotly  
**输入数据**：`df_daily_agg`  
**展示内容**：
- X轴：日期；
- Y轴：当日总差异；
- 堆积柱：不同颜色代表 `delta_price`、`delta_fill`、`delta_fees`。  
**要求**：
- 支持按日期范围缩放；
- 悬停显示当日各分项差异金额。


### 6.3 价格差异散点图
**工具**：Plotly  
**输入数据**：`df_attribution`（过滤 `q_common > 0` 的记录）  
**展示内容**：
- X轴：信号触发时的涨跌幅（`(trigger_price - prev_close) / prev_close`，需额外接入前收盘价数据，无则用 `trigger_price`）；
- Y轴：`delta_price`；
- 点颜色：区分买入/卖出（`direction`）。  
**要求**：
- 悬停显示 `signal_id`、`symbol`、`trigger_price`、`bt_price`、`sim_price`。


## 7. 验收标准
### 7.1 单元测试用例
**测试数据**：
```python
# 信号表
df_signals = pd.DataFrame([{
    'signal_id': 'SIG_001',
    'timestamp': pd.Timestamp('2026-03-17 09:35:00'),
    'symbol': '600519.SH',
    'direction': 1,
    'target_qty': 100,
    'trigger_price': 1800.0
}])

# 回测成交表（1笔成交）
df_bt_exec = pd.DataFrame([{
    'signal_id': 'SIG_001',
    'exec_id': 'BT_001',
    'exec_ts': pd.Timestamp('2026-03-17 09:35:01'),
    'exec_price': 1800.0,
    'exec_qty': 100,
    'fee': 5.0
}])

# 模拟盘成交表（2笔成交，需聚合）
df_sim_exec = pd.DataFrame([
    {
        'signal_id': 'SIG_001',
        'exec_id': 'SIM_001',
        'exec_ts': pd.Timestamp('2026-03-17 09:35:02'),
        'exec_price': 1800.5,
        'exec_qty': 50,
        'fee': 2.5
    },
    {
        'signal_id': 'SIG_001',
        'exec_id': 'SIM_002',
        'exec_ts': pd.Timestamp('2026-03-17 09:35:03'),
        'exec_price': 1801.0,
        'exec_qty': 30,
        'fee': 1.5
    }
])
```

**预期结果**：
1.  聚合后模拟盘：`sim_price = (1800.5*50 + 1801.0*30)/80 = 1800.6875`，`sim_qty=80`，`sim_fee=4.0`；
2.  `q_common = min(100, 80) = 80`，`q_diff = 80-100 = -20`；
3.  `delta_price = (1800.6875 - 1800.0) * 80 * 1 = 55.0`；
4.  `delta_fill = (-20) * 1800.0 * 1 = -36000.0`；
5.  `delta_fees = 5.0 - 4.0 = 1.0`；
6.  `delta_total = 55.0 - 36000.0 + 1.0 = -35944.0`。




