# 测试说明（生产架构）

## 运行

```bash
pip install -e ".[dev]"
pytest tests -v
```

## 覆盖

| 文件 | 内容 |
|------|------|
| `tests/unit/test_production_core.py` | Schema 校验、防幻觉、Stub 编排 GMV/澄清、别名 |
| `tests/api/test_api_smoke.py` | Health、工具 Schema 暴露、对话取数 |

旧版关键词 Agent 的 UAT 已移除；回归以「工具 Schema + Orchestrator」路径为准。
