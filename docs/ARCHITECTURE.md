# Emmerce Agent 生产架构说明

## 1. 为什么要这样构建

本项目要同时满足三件事：

1. **自然语言开放**：用户说法多变，不能靠 `if "GMV" in text` 穷举；
2. **数据口径封闭**：标准指标数值必须来自受控工具/数仓，禁止模型心算；
3. **可演进、可审计**：换模型、加渠道、加指标时，不推倒 Agent 核心。

因此采用 **分层 + 端口适配器（Hexagonal）**，而不是「一个 agent.py 里串所有逻辑」。

```text
interfaces/api          ← HTTP/SSE，薄，只做协议转换与鉴权注入
        ↓
application             ← 用例：对话编排、工具循环、结果校验、记忆写入
        ↓
domain                  ← 纯业务：指标目录、租户、工具契约、消息块
        ↑
infrastructure          ← 实现细节：LLM、MCP/数仓、记忆存储、配置
```

依赖方向 **只允许向内**：`interfaces → application → domain`，`infrastructure` 实现 `application` 定义的 Port，**domain 不依赖框架、不依赖 LLM SDK**。

---

## 2. 目录职责与优点

| 目录 | 职责 | 这样拆的优点 |
|------|------|----------------|
| `domain/` | 指标字典、租户上下文、工具 JSON Schema 契约、消息协议、领域错误 | 业务规则可单测；换 FastAPI/换存储也不动核心模型 |
| `application/` | Agent 编排、工具注册表、结果校验器、会话用例 | 产品流程集中；可替换 LLM/工具实现做集成测试 |
| `application/ports.py` | LLM / Warehouse / Memory / Clock 等接口 | 依赖倒置：应用定义需要什么，基础设施去实现 |
| `infrastructure/llm/` | BaseLLMAdapter、通义/智谱适配器、本地 Stub | 新增大模型只加适配器，不改编排 |
| `infrastructure/tools/` | 工具网关、订单库存/计算/导出执行器 | 工具与 Agent 解耦；权限、限流、审计可统一做 |
| `infrastructure/memory/` | Working/Episodic/Semantic 实现 | 可从内存换到 PG+Qdrant，不改 application |
| `infrastructure/warehouse/` | 数仓端口实现（内存/SQL/MaxCompute） | Demo 与生产切换只改装配 |
| `infrastructure/config/` | Settings（环境变量） | 密钥与部署参数不进代码 |
| `interfaces/api/` | FastAPI 路由 | 界面层可测、可替换为 gRPC 而不动业务 |
| `web/` | 商家端 SPA | 前后端分离；契约对齐 `domain` 消息协议 |

旧的扁平模块（`agent.py` / `tools.py` 等）已降级为兼容导出或删除，**新代码以本结构为准**。

---

## 3. 运行时主链路（生产形态）

```text
用户自然语言
    → ContextBuilder 组装 [Role&Rules|Task|Evidence|Context]
    → LLM（带 tools JSON Schema）决定：
         a) 直接澄清 或
         b) tool_call(name, arguments)
    → ToolGateway：Schema 校验 → RBAC → 限流 → 执行 → 审计日志
    → ResultValidator：回答中的数值必须能在 tool result 中追溯
    → LLM 基于工具 JSON 生成解读（禁止无来源数字）
    → 消息协议 MessageBlock[] 返回前端
    → 可信结论异步写入 EpisodicMemory
```

**为什么要 Schema？**  
模型输出必须是「可机器执行」的参数对象；Schema 是工具插座规格，用于校验、安全白名单、多模型统一。

**为什么要校验器？**  
即使 LLM tool_call 成功，解读阶段仍可能编造数字；校验器保证「对外报出的标准指标值 ⊆ 本轮工具返回值」。

**为什么指标要先归一到 metric_code？**  
别名/口语由 LLM 或别名表映射到字典编码，工具只认 `metric_code`，口径单一、可审计。

---

## 4. 与 Demo 关键词路由的差异

| | Demo（旧） | 生产（现） |
|--|-----------|-----------|
| 意图理解 | 字符串包含 | LLM + 工具 Schema / 槽位 |
| 取数 | 硬编码分支 | 工具注册表分发 |
| 防幻觉 | 弱 | ResultValidator 强制 |
| 换模型 | 改 Agent | 加 Adapter |
| 换数仓 | 改 FakeWarehouse 调用点 | 换 WarehousePort 实现 |

---

## 5. 配置与密钥

通过环境变量（见 `infrastructure/config/settings.py`）：

- `EMMERCE_LLM_PROVIDER=stub|qwen|zhipu`
- `EMMERCE_LLM_API_KEY=...`
- `EMMERCE_LLM_BASE_URL=...`
- `EMMERCE_WAREHOUSE_BACKEND=memory|mysql`（扩展点）

本地无 `stub` 即可做编排联调；生产切 `qwen` 并注入密钥。

---

## 6. 扩展指南（一句话）

- **新指标**：改 `domain/metrics/catalog.py` + Gateway 计算分支，不必改编排。  
- **新工具**：在 `domain/tools/specs.py` 登记 Schema，在 `infrastructure/tools/gateway.py` 注册 Handler。  
- **新模型**：实现 `LLMPort` / 继承 `OpenAICompatibleAdapter`，在 `composition.build_llm` 注入。  
- **新渠道数据源**：实现 `WarehousePort`，在 composition 切换装配。

## 7. 源码树（权威）

```text
src/emmerce_agent/
  domain/                 # 纯业务，零框架依赖
    metrics/catalog.py    # 指标字典 SSOT
    tools/specs.py        # 工具 JSON Schema
    tools/validation.py   # Schema 校验
    context/builder.py    # ContextBuilder
    messaging.py          # MessageBlock 协议
    tenancy.py            # 租户上下文
    errors.py
  application/            # 用例
    ports.py              # LLM/Warehouse/Memory/Tool 端口
    agent/
      orchestrator.py     # tool-calling 主循环
      result_validator.py # 防幻觉校验
      prompts.py
  infrastructure/         # 适配器实现
    composition.py        # 装配根（DI）
    config/settings.py
    llm/                  # stub | qwen | zhipu
    tools/gateway.py      # Schema→RBAC→执行
    memory/stores.py
    warehouse/
    security/
  interfaces/api/         # FastAPI
  api/                    # 兼容旧入口 re-export
web/                      # 商家端 SPA
docs/ARCHITECTURE.md
docs/PRD-*.md
.env.example
```

启动（默认 stub LLM，生产可切 qwen）：

```bash
pip install -e ".[dev]"
# 可选: copy .env.example → 环境变量 EMMERCE_LLM_PROVIDER=qwen
python -m uvicorn emmerce_agent.interfaces.api.main:app --reload --port 8000
```
