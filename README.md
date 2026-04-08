<div align="center">

# QuantAgent OS

[English](#english) | [中文](#chinese)

A modern, agent-driven quantitative trading system with a microservices architecture.
基于微服务架构的现代化、智能体驱动量化交易系统。

</div>

---

<a id="english"></a>
## 🇬🇧 English

### ⚠️ Disclaimer
**This project is currently designed and intended primarily for paper trading, strategy research, and educational purposes.** Cryptocurrency and quantitative trading involve significant financial risk. The developers and contributors of this project assume no liability for any financial losses incurred from the use of this software. Users are strongly advised against using this system for real-money trading without extensive independent validation.

### 📖 Overview
QuantAgent is a modular, high-performance operating system designed for quantitative trading. It integrates an event-driven trading engine with Large Language Model (LLM) agents, providing an end-to-end platform capable of strategy backtesting, interactive historical replay, and simulated execution.

### ✨ Core Capabilities
*   **Multi-Mode Trading Engine**: Built on an asynchronous event bus (`TradingBus`), the engine supports Backtesting, Paper Trading, and an interactive **Historical Replay** mode with adjustable simulation speeds (1x, 10x, 100x). *(Note: The infrastructure for Live Trading is implemented but is disconnected by default for safety reasons).*
*   **Professional Trading Terminal**: A web-based frontend developed with Next.js 15 and Tailwind CSS 4. It integrates TradingView's `lightweight-charts` for optimized K-line rendering and utilizes `recharts` for equity curve visualization and parameter stability analysis.
*   **Agentic AI Integration**: Features native integration with multiple LLM providers (OpenAI, Ollama, OpenRouter). The system utilizes PostgreSQL with the `pgvector` extension to implement Retrieval-Augmented Generation (RAG), enabling agents to store memories, analyze market context, and assist in strategy selection.
*   **Advanced Quantitative Analysis**: 
    *   **Walk-Forward Analysis (WFA)**: Includes a WFA engine that utilizes rolling out-of-sample testing to evaluate parameter robustness and mitigate overfitting.
    *   **Dynamic Strategy Selection**: A mechanism that continuously evaluates, ranks, and filters multiple strategies based on real-time multi-dimensional metrics, dynamically reallocating capital weights accordingly.
*   **Risk Management Framework**: Implements pre-trade risk controls, including a global kill switch, order deviation limits ("fat-finger" protection), position concentration thresholds (capped at 20%), and maximum drawdown limits. *(Note: Complex macro risk checks are intentionally bypassed during historical replay to allow for pure strategy signal validation).*
*   **Distributed Infrastructure**: 
    *   **Backend Logic**: Python 3.12 and FastAPI.
    *   **Execution Gateway**: Go and NATS message bus for low-latency order routing.
    *   **Data Storage**: ClickHouse for large-scale OHLCV time-series data, Redis for distributed caching, and PostgreSQL for relational data management.

### 🏗️ Technology Stack
*   **Frontend**: React 19, Next.js 15 (App Router), shadcn/ui, TypeScript.
*   **Backend**: Python 3.12, FastAPI, SQLAlchemy, Alembic, CCXT.
*   **Gateway**: Go, NATS.
*   **Databases**: PostgreSQL 16 (pgvector), Redis 7, ClickHouse 24.
*   **Deployment**: Docker Compose.

### 🚀 Getting Started
Ensure that Docker and Docker Compose are installed on your system.

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/QuantAgent.git
cd QuantAgent

# 2. Configure environment variables
cp .env.example .env
# Edit the .env file to configure API keys, proxies, and database credentials.

# 3. Start the services
docker-compose up -d
```
Once the containers are running, the trading terminal will be accessible at `http://localhost:3002`, and the backend API documentation will be available at `http://localhost:8002/docs`.

---

<a id="chinese"></a>
## 🇨🇳 中文

### ⚠️ 免责声明
**本项目目前主要设计并定位于模拟交易（Paper Trading）、策略研究和技术交流。** 加密货币与量化交易涉及极高的财务风险。本项目开发者与贡献者不对因使用本软件而导致的任何直接或间接资金损失承担责任。强烈建议用户不要在未经独立、全面验证的情况下，将本系统直接用于真实资金的实盘交易。

### 📖 项目概述
QuantAgent 是一个模块化、高性能的量化交易操作系统。该项目将事件驱动的交易引擎与大语言模型（LLM）智能体相结合，提供了一个涵盖策略回测、交互式历史回放及模拟执行的端到端量化平台。

### ✨ 核心功能
*   **多模式交易引擎**: 基于异步事件总线（`TradingBus`）构建，支持极速回测（Backtesting）、模拟盘（Paper Trading），以及支持倍速调节（1x, 10x, 100x）的**交互式历史回放（Historical Replay）**模式。*（注：实盘交易的底层基础设施已实现，但出于资金安全考虑，当前默认处于断开状态）。*
*   **专业交互终端**: 前端基于 Next.js 15 与 Tailwind CSS 4 构建。深度集成了 TradingView 的 `lightweight-charts` 以保障 K 线图表的高性能渲染，并使用 `recharts` 进行资产收益曲线及参数稳定性分析的可视化。
*   **Agentic AI 集成**: 原生支持多种 LLM 供应商（OpenAI, Ollama, OpenRouter）。系统利用 PostgreSQL 的 `pgvector` 扩展实现了基于检索增强生成（RAG）的智能体记忆系统，能够进行具备上下文感知的市场分析与策略辅助选择。
*   **高级量化评估体系**: 
    *   **向前走查分析 (WFA)**: 内置 WFA 引擎，通过滚动样本外测试来评估参数的鲁棒性，有效降低策略过拟合风险。
    *   **动态策略选择 (Dynamic Selection)**: 基于收益、风险等多维度的实时评分，自动对多策略组合进行评估、排名与末位淘汰，并动态调整资金分配权重。
*   **风控管理框架**: 实现了全面的交易前置风控机制，包含全局熔断（Kill Switch）、价格偏离拦截（防胖手指）、单币种仓位集中度限制（上限 20%）及最大回撤保护。*（注：在历史回放模式下，系统会自动跳过复杂的宏观风控规则，以确保对策略原始信号的客观验证）。*
*   **分布式基础设施**: 
    *   **业务逻辑**: 采用 Python 3.12 与 FastAPI 处理复杂的量化逻辑。
    *   **执行网关**: 采用 Go 语言配合 NATS 消息总线构建底层网关，保障订单路由的低延迟。
    *   **数据存储**: 使用 ClickHouse 存储海量 OHLCV 时序数据，Redis 提供分布式缓存与锁，PostgreSQL 管理关系型数据。

### 🏗️ 技术架构
*   **前端**: React 19, Next.js 15 (App Router), shadcn/ui, TypeScript.
*   **后端**: Python 3.12, FastAPI, SQLAlchemy, Alembic, CCXT.
*   **底层网关**: Go, NATS.
*   **数据库**: PostgreSQL 16 (pgvector), Redis 7, ClickHouse 24.
*   **部署**: 基于 Docker Compose 的全容器化部署。

### 🚀 快速开始
请确保部署环境已安装 Docker 与 Docker Compose。

```bash
# 1. 克隆代码仓库
git clone https://github.com/yourusername/QuantAgent.git
cd QuantAgent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入必要的 API 密钥及代理配置。

# 3. 启动所有服务
docker-compose up -d
```
服务启动完成后，请通过浏览器访问 `http://localhost:3002` 进入交易终端。后端 API 文档可通过 `http://localhost:8002/docs` 访问。