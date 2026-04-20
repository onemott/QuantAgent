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

### 📖 项目简介
QuantAgent OS 是一个模块化、高性能的量化交易操作系统。该项目将事件驱动的交易引擎与大语言模型（LLM）智能体相结合，提供了一个涵盖策略回测、交互式历史回放及模拟执行的端到端量化平台。

### ✨ 核心功能
*   **多模式交易引擎**：基于异步事件总线（`TradingBus`）构建，支持极速回测（Backtesting）、模拟盘（Paper Trading），以及支持倍速调节（1x, 10x, 100x）的**交互式历史回放（Historical Replay）**模式。*（注：实盘交易的底层基础设施已实现，但出于资金安全考虑，当前默认处于断开状态）。*
*   **专业交互终端**：前端基于 Next.js 15 与 Tailwind CSS 4 构建。深度集成了 TradingView 的 `lightweight-charts` 以保障 K 线图表的高性能渲染，并使用 `recharts` 进行资产收益曲线及参数稳定性分析的可视化。
*   **Agentic AI 集成**：原生支持多种 LLM 供应商（OpenAI, Ollama, OpenRouter）。系统利用 PostgreSQL 的 `pgvector` 扩展实现了基于检索增强生成（RAG）的智能体记忆系统，能够进行具备上下文感知的市场分析与策略辅助选择。
*   **高级量化评估体系**：
    *   **向前走查分析 (WFA)**：内置 WFA 引擎，通过滚动样本外测试来评估参数的鲁棒性，有效降低策略过拟合风险。
    *   **动态策略选择 (Dynamic Selection)**：基于收益、风险等多维度的实时评分，自动对多策略组合进行评估、排名与末位淘汰，并动态调整资金分配权重。
*   **风控管理框架**：实现了全面的交易前置风控机制，包含全局熔断（Kill Switch）、价格偏离拦截（防胖手指）、单币种仓位集中度限制（上限 20%）及最大回撤保护。*（注：在历史回放模式下，系统会自动跳过复杂的宏观风控规则，以确保对策略原始信号的客观验证）。*

### 🏗️ 技术栈
| 层级 | 技术 |
|------|------|
| 前端 | React 19, Next.js 15, TypeScript, Tailwind CSS 4, shadcn/ui |
| 后端 | Python 3.12, FastAPI, SQLAlchemy, Alembic, CCXT |
| 网关 | Go 1.22, NATS |
| 数据库 | PostgreSQL 16 (pgvector), Redis 7, ClickHouse 24 |
| 部署 | Docker, Docker Compose |

### 🖥️ 环境要求

**Docker 部署（推荐）**
- Docker 20.10+
- Docker Compose 2.0+

**本地开发（可选）**
- Python 3.11+
- Node.js 18+
- Go 1.21+
- PostgreSQL 16, Redis 7, ClickHouse 24, NATS 2.10

### 🚀 快速开始（Docker Compose 部署）

```bash
# 1. 克隆代码仓库
git clone https://github.com/yourusername/QuantAgent.git
cd QuantAgent

# 2. 配置根目录环境变量
cp .env.example .env
# 编辑 .env 文件，填入必要的 API 密钥及代理配置

# 3. 配置后端环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env 文件，配置数据库连接和 LLM 参数

# 4. 一键启动所有服务
docker compose up -d
```

**访问地址**
| 服务 | 地址 | 说明 |
|------|------|------|
| 前端界面 | http://localhost:3002 | 交易终端 |
| 后端 API | http://localhost:8002 | FastAPI 服务 |
| API 文档 | http://localhost:8002/docs | Swagger UI |
| PostgreSQL | localhost:5435 | 数据库外部端口 |
| Redis | localhost:6382 | 缓存外部端口 |
| ClickHouse HTTP | localhost:8124 | 时序数据库 |
| NATS | localhost:4223 | 消息队列 |

### 🔧 环境变量配置说明

项目使用两个环境变量文件：

**1. 根目录 .env（Docker Compose 使用）**
- 主要配置：应用基础设置、数据库连接、缓存、消息队列、交易所 API 密钥、代理设置、LLM 配置
- 必填项：`DATABASE_URL`, `REDIS_URL`, `NATS_URL`, `SECRET_KEY`
- 可选但建议配置：`BINANCE_API_KEY`, `BINANCE_SECRET_KEY`（用于获取行情数据）

**2. backend/.env（后端服务使用）**
- 主要配置：与根目录类似，但用于本地开发时直接运行后端
- 特别注意：本地开发时数据库连接应使用 `localhost` 而非容器名

**LLM 配置说明**
系统支持多种 LLM 提供商：
- **Ollama（本地）**：设置 `LLM_PROVIDER=ollama` 和 `OLLAMA_BASE_URL=http://127.0.0.1:11434`
- **OpenAI 兼容 API**：设置 `LLM_PROVIDER=openai`，配置 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`
  - 支持阿里云 DashScope: `https://dashscope.aliyuncs.com/compatible-mode/v1`
  - 支持 OpenAI 官方: `https://api.openai.com/v1`
- **OpenRouter**：设置 `LLM_PROVIDER=openrouter`

### 💻 本地开发（不使用 Docker）

**后端开发**
```bash
cd backend

# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，确保数据库连接指向本地服务

# 4. 启动服务
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

**端口说明**
- Docker 部署时：后端容器内部使用 8000 端口，映射到宿主机 8002 端口
- 本地开发时：后端直接监听 8002 端口，前端需对应修改 API 地址（如 `http://localhost:8002`）

**前端开发**
```bash
cd frontend

# 1. 安装依赖
npm install

# 2. 启动开发服务器
npm run dev
# 默认运行在 http://localhost:3000
```

**网关开发**
```bash
cd gateway

# 1. 安装依赖
go mod tidy

# 2. 编译
go build -o gateway ./cmd/main.go

# 3. 运行
./gateway
```

### 🗄️ 数据库初始化

**Docker 方式（自动）**
- 首次启动时，后端容器会自动执行 Alembic 迁移创建表结构
- 数据持久化通过 Docker volumes 管理

**手动方式（Alembic 迁移）**
```bash
cd backend

# 执行迁移
alembic upgrade head

# 创建新迁移（开发时使用）
alembic revision --autogenerate -m "描述"
```

### 📁 项目结构

```
QuantAgent/
├── backend/          # Python FastAPI 后端服务
│   ├── app/          # 核心业务逻辑
│   │   ├── agents/   # AI 智能体
│   │   ├── api/      # API 路由
│   │   ├── core/     # 核心组件（交易引擎、事件总线）
│   │   ├── models/   # 数据模型
│   │   ├── services/ # 业务服务
│   │   └── strategies/ # 交易策略
│   ├── init-scripts/ # 数据库初始化脚本
│   ├── migrations/   # Alembic 迁移文件
│   └── main.py       # 应用入口
├── frontend/         # Next.js 前端应用
│   ├── app/          # 页面路由
│   ├── components/   # React 组件
│   └── lib/          # 工具函数
├── gateway/          # Go 网关服务
│   └── cmd/          # 应用入口
├── docker-compose.yml # Docker 编排配置
└── .env.example      # 环境变量模板
```

**各模块职责**
- **backend/**：处理业务逻辑、策略执行、数据管理、AI 智能体交互
- **frontend/**：提供交易界面、图表展示、策略配置、实时监控
- **gateway/**：负责与交易所通信、订单执行、行情数据推送

### 📝 注意事项

1. **端口映射**：前端服务通过 `3002:3000` 映射，外部访问请使用 3002 端口
2. **代理配置**：如处于受限网络环境，请配置 `HTTP_PROXY` 和 `HTTPS_PROXY`
3. **Ollama 访问**：Docker 内访问宿主机 Ollama 使用 `host-gateway`，本地开发使用 `127.0.0.1`
4. **首次启动**：数据库初始化可能需要一些时间，请等待后端服务完全启动
