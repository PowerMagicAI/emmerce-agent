# Emmerce Agent

电商数据生产 + 多步分析 Agent。面向「用 Python + LLM 做抽取/分类/校验，再用数据+模型解决经营问题」。

## 方法判断（规则 / 统计 / LLM）

| 问题 | 方法 | 原因 |
|------|------|------|
| 标题抽取、类目关键词、无效订单 | **规则** | 硬特征稳定、可复现、便宜 |
| 价格异常、销量基线预测 | **统计** | IQR / 窗口均值×星期权重，数字不交给模型心算 |
| 广告 ROI、预警阈值 | **规则聚合** | 演示投放表 / 退款率 / 假 OCR，可换成真实平台 |
| 记忆检索 | **哈希词袋向量** | `hashed_bow_v1` 代替 Qdrant；可替换真实 embedding |
| 口语理解、澄清、解释、灰色类目 | **LLM** | 语言与歧义；不负责编造指标 |

Agent 负责编排工具；同一套函数也可 CLI / HTTP 批跑。

## 快速开始

```bash
# API
set PYTHONPATH=src
python -m uvicorn emmerce_agent.interfaces.api.main:app --reload --port 8000

# 前端
cd web && npm install && npm run dev
```

对话：http://127.0.0.1:5173  
数据生产：http://127.0.0.1:5173/data-ops  
预警中心：http://127.0.0.1:5173/alerts

演示数据来自 `datasets/demo/`（CSV，可复现）。可用 `EMMERCE_DATASET_DIR` 覆盖路径。

LLM 默认可用 stub（CI）。真实模型见 `.env.example`（`deepseek` / `modelscope` 等）。

需要 **Python 3.11+**（推荐 3.12；勿用 Anaconda 3.8）。

API 使用签名令牌：前端会自动 `POST /api/v1/auth/login`（演示账号 `owner` / `analyst`）。不要再伪造 `X-Tenant-Id`。

```bash
python -m emmerce_agent.cli eval
python -m emmerce_agent.cli eval --live
```

```bash
# 会话落盘（默认 memory；sqlite 重启后仍在）
set EMMERCE_SESSION_BACKEND=sqlite
set EMMERCE_SESSION_SQLITE=./data/emmerce_sessions.db
```

运营观测：`GET /api/v1/admin/ops`（需 owner）。对话 `/chat/stream` 会推送真实工具步骤（`plan` / `llm` / `tool` / `validate`）。

## 可复用入口

```bash
python -m emmerce_agent.cli pipeline --shop shop_a1
python -m emmerce_agent.cli workflow product_qc
python -m emmerce_agent.cli workflow ops_diagnosis
python -m emmerce_agent.cli workflow ad_diagnosis
python -m emmerce_agent.cli anomaly
python -m emmerce_agent.cli eval
```

命名工作流：

- `product_qc`：假 OCR + 抽取→分类→校验→价格异常
- `ops_diagnosis`：GMV → 无效单 → 价格异常 → 星期权重预测 → 演示广告 ROI
- `ad_diagnosis`：广告聚合 → 假 OCR 图文 → 阈值预警

## 测试

```bash
pytest tests -q
```

包含 golden 工具路由（`eval/golden_tools.json`）。

## 结构

- `datasets/demo` 可复现 CSV（订单 / 商品 / 日销 / 广告 / 假 OCR / 预警）
- `application/data_pipeline` 数据生产（属性槽、违禁词、假 OCR、图文一致）
- `application/analytics` 价格异常 / 无效单 / 季节权重预测 / 广告 / 预警 / 哈希向量
- `application/workflow` 显式多步工作流（含投放诊断）
- `application/agent` LLM 工具循环 + Schema + 数值 grounding
- `application/ops` 工具成功率 / 拦截率计数
