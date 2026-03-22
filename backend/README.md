# AI PJM Backend

AI-powered Project Management Backend Service

## 项目定位

本项目是"安全型团队提效 AI 工作台"的后端实现。

核心业务闭环：**输入 → Item（事项）→ Analysis（分析）→ Output（输出物）→ Adopted（采用）**

## 技术栈

- **Python 3.11+**
- **FastAPI** - Web 框架
- **SQLAlchemy 2.0** - ORM (async)
- **asyncpg** - PostgreSQL 异步驱动
- **Alembic** - 数据库迁移
- **Pydantic v2** - 数据验证
- **Celery** - 异步任务队列（预留）
- **Redis** - 缓存和消息队列（预留）

## 核心主对象

系统只有 3 个主业务对象：

1. **Item** - 事项（客户反馈、需求、Bug、工单等）
2. **Analysis** - 影响分析
3. **Output** - 输出物（PRD、测试点、会议纪要等）

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，配置数据库连接等
```

### 3. 初始化数据库

```bash
# 创建数据库
createdb ai_pjm

# 运行迁移
alembic upgrade head
```

### 4. 启动服务

```bash
# 开发模式
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 5. 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 项目结构

```
backend/
├── app/
│   ├── main.py                 # FastAPI 应用入口
│   ├── core/                   # 核心基础设施
│   ├── common/                 # 通用工具
│   ├── modules/                # 业务模块
│   │   ├── item/              # Item 模块
│   │   ├── analysis/          # Analysis 模块
│   │   ├── output/            # Output 模块
│   │   ├── workbench/         # Workbench 模块
│   │   └── audit/             # ActionLog 模型
│   ├── ai/                    # AI 服务抽象层
│   ├── tasks/                 # Celery 任务
│   └── api/                   # API 路由聚合
├── migrations/                # 数据库迁移
└── tests/                     # 测试
```

## 开发规范

### 代码检查

```bash
# 格式化
black app/

# Lint
ruff check app/

# 类型检查
mypy app/
```

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_health.py

# 查看覆盖率
pytest --cov=app tests/
```

## 当前实现状态

### ✅ 已完成（工程初始化）
- FastAPI 项目骨架
- SQLAlchemy + Alembic 配置
- ActionLog 模型（用于审计日志）
- AI 抽象层接口定义
- 基础测试框架

### 🚧 进行中（下一阶段：Item 最小闭环）
- Item / ItemSuggestion 模型
- Item CRUD API
- Item 状态流转
- Understanding Service（Mock）

### 📋 待实现
- Analysis 闭环
- Output 闭环
- Workbench 聚合
- 真实 AI 模型接入

## 许可证

MIT
