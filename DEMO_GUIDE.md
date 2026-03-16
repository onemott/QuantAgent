# QuantAgent 全功能演示指南

这份指南旨在帮助您通过一系列结构化的演示，完整展示 QuantAgent 量化交易系统的核心功能、技术架构及系统韧性。

## 0. 环境准备 (Prerequisites)

在开始演示前，请确保开发环境已就绪。

### 核心配置
1.  **API Key 配置**: 确保 `.env` 文件中已配置 `OPENAI_API_KEY` (或 Ollama URL) 和 `BINANCE_API_KEY` (可选，部分公开数据不需要)。
2.  **网络环境**: 确保 Docker 容器可以访问外网（Binance API 和 CoinGecko API）。
    *   *注意*: 如果在中国大陆地区，请确认 `docker-compose.yml` 中的 `HTTP_PROXY` 指向了正确的本地代理地址（如 `host.docker.internal:7897`）。

### 启动系统
```bash
# 在项目根目录执行
docker-compose up -d

# 检查服务状态 (确保 backend, frontend, postgres, redis, clickhouse 均为 Up)
docker-compose ps
```

### 访问入口
*   **前端界面**: [http://localhost:3000](http://localhost:3000)
*   **后端 API 文档**: [http://localhost:8000/docs](http://localhost:8000/docs)
*   **数据库管理 (可选)**: ClickHouse (8123), Postgres (5432)

---

## 1. 核心功能演示 (Core Features)

### 场景一：多源行情监控 (Market Dashboard)
**目标**: 展示系统整合不同数据源（Binance + CoinGecko）的能力。

1.  **打开仪表盘**: 访问 `http://localhost:3000/dashboard`。
2.  **查看实时行情**:
    *   展示 BTC/USDT, ETH/USDT 的实时 K 线图。
    *   切换时间周期 (Timeframe): 从 `1h` 切换到 `15m`，展示系统响应速度。
    *   *技术点*: 数据直接来自 Binance 接口，通过后端转发解决跨域问题。
3.  **市场概览 (CoinGecko 集成)**:
    *   滚动到 "Trending Coins" (热门币种) 板块。
    *   展示当前市场搜索热度最高的币种。
    *   *讲解*: 这是一个多源数据融合系统，不仅看价格，还关注市场热度。
4.  **价格对比**:
    *   使用“价格对比”功能，展示同一币种在不同交易所/数据源的价差（如有）。

### 场景二：策略回测引擎 (Strategy Backtesting)
**目标**: 展示量化核心能力——策略验证与绩效分析。

1.  **进入回测页**: 访问 `http://localhost:3000/backtest`。
2.  **配置策略**:
    *   **策略类型**: 选择 `Bollinger Bands` (布林带策略) 或 `RSI Mean Reversion`。
    *   **交易对**: 输入 `BTCUSDT`。
    *   **周期**: 选择 `1d` (日线)。
    *   **参数**: 设置 `period=20`, `std_dev=2.0`。
    *   **初始资金**: 设置 `10000` USDT。
3.  **执行回测**: 点击 "Run Backtest"。
4.  **结果分析 (关键演示点)**:
    *   **资金曲线 (Equity Curve)**: 指着图表展示策略收益 vs "买入持有" (Baseline) 的对比。如果策略跑赢了 Bitcoin 本身，这是最大的亮点。
    *   **交易标记**: 在 K 线图上查看 `B` (Buy) 和 `S` (Sell) 的标记点，验证买卖逻辑是否符合预期。
    *   **核心指标**: 逐一解读 `Sharpe Ratio` (夏普比率), `Max Drawdown` (最大回撤), `Win Rate` (胜率)。

### 场景三：AI 智能助手 (AI Agent Terminal)
**目标**: 展示 LLM (大模型) 在量化分析中的应用。

1.  **进入终端**: 访问 `http://localhost:3000/terminal`。
2.  **自然语言交互**:
    *   输入: *"帮我分析一下现在的 BTC 行情趋势"*
    *   或者: *"创建一个基于均线交叉的交易策略"*
3.  **观察反馈**:
    *   展示 Agent 如何调用底层数据工具 (Tools) 获取信息，然后生成人类可读的分析报告。
    *   *技术点*: 提及后端 `app/agents` 目录下的多 Agent 协作架构 (`Coordinator` + `TrendAgent`)。

---

## 2. 系统韧性与降级演示 (Resilience & Fallback)

**目标**: 展示系统在极端情况下的稳定性（根据项目核心记忆定制）。

### 场景：Binance 接口故障/网络中断
*背景*: 交易所接口经常会因为网络原因超时或返回 500 错误。

1.  **模拟故障**:
    *   方法 A: 暂时断开开发机网络。
    *   方法 B: 在代码中临时修改 API 地址为一个不存在的地址 (模拟超时)。
2.  **观察前端行为**:
    *   刷新行情页面。
    *   **预期结果**: 页面**不会白屏或崩溃**。
    *   系统会自动切换到 **"降级模式" (Degraded Mode)**，展示本地缓存的演示数据或友好的错误提示。
    *   *讲解*: 强调这是企业级应用必须具备的容错设计，保证用户体验不中断。

---

## 3. 技术架构展示 (Architecture Deep Dive)
*(面向技术受众)*

1.  **高性能存储**:
    *   展示 `docker-compose.yml` 中的 `ClickHouse` 服务。
    *   解释为何使用 ClickHouse 存储 K 线数据（列式存储，查询速度快，适合时间序列）。
2.  **消息驱动**:
    *   提及 `NATS` 消息队列，用于解耦行情数据的接收与处理。
3.  **微服务设计**:
    *   Backend (FastAPI) 处理业务逻辑。
    *   Gateway (Go) 处理高并发 WebSocket 连接 (如有)。

---

## 演示结语
总结 QuantAgent 的特点：
1.  **全栈闭环**: 从数据获取、存储、分析到回测、交易。
2.  **AI 赋能**: 集成 LLM 降低使用门槛。
3.  **高可用**: 完善的降级策略和稳健的架构设计。
