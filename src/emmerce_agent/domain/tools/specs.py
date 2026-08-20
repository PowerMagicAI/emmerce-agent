"""Tool contracts: name + JSON Schema. LLM and Gateway share this SSOT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object
    # which metric_codes this tool may emit (for validator allowlist)
    emits_metrics: tuple[str, ...] = ()

    def openai_tool(self) -> dict[str, Any]:
        """OpenAI / 通义兼容的 tools[] 条目。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def build_tool_specs(*, allowed_metric_codes: list[str], allowed_shops_hint: str = "调用方租户可见店铺") -> list[ToolSpec]:
    """Production tool surface for P0 analytics agent."""
    metric_enum = allowed_metric_codes
    return [
        ToolSpec(
            name="query_metric",
            description=(
                "按标准指标编码查询聚合数值。用户口语需先映射到 metric_code "
                f"（允许值: {', '.join(metric_enum)}）。禁止臆造数值。"
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string", "description": f"店铺ID（{allowed_shops_hint}）"},
                    "metric_code": {
                        "type": "string",
                        "enum": metric_enum,
                        "description": "指标字典中的标准编码",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "起始日期 YYYY-MM-DD，可空表示今日",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "结束日期 YYYY-MM-DD，可空表示今日",
                    },
                },
                "required": ["shop_id", "metric_code"],
            },
            emits_metrics=tuple(metric_enum),
        ),
        ToolSpec(
            name="compare_metric",
            description=(
                "对比同一指标在两段日期的工具计算结果（环比/对比）。"
                "禁止模型自行相减。period A 与 period B 均为 YYYY-MM-DD。"
            ),
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string"},
                    "metric_code": {"type": "string", "enum": metric_enum},
                    "date_from_a": {"type": "string", "description": "区间A起始 YYYY-MM-DD"},
                    "date_to_a": {"type": "string", "description": "区间A结束 YYYY-MM-DD"},
                    "date_from_b": {"type": "string", "description": "区间B起始 YYYY-MM-DD"},
                    "date_to_b": {"type": "string", "description": "区间B结束 YYYY-MM-DD"},
                },
                "required": [
                    "shop_id",
                    "metric_code",
                    "date_from_a",
                    "date_to_a",
                    "date_from_b",
                    "date_to_b",
                ],
            },
            emits_metrics=tuple(metric_enum),
        ),
        ToolSpec(
            name="query_slow_moving",
            description="查询指定月份滞销 SKU 汇总；可请求明细。用于滞销/不动销分析与跨月对比。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string"},
                    "month": {"type": "string", "description": "YYYY-MM"},
                    "include_detail": {"type": "boolean", "default": False},
                },
                "required": ["shop_id", "month"],
            },
            emits_metrics=("slow_moving_count",),
        ),
        ToolSpec(
            name="export_report",
            description="将本轮分析结果导出为文件，返回仅本人可下载的链接（24h 有效）。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "filename": {"type": "string"},
                    "rows": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "导出行（已聚合，勿含未脱敏隐私）",
                    },
                },
                "required": ["filename", "rows"],
            },
        ),
        ToolSpec(
            name="ask_clarification",
            description="当时间范围、口径、店铺范围歧义时，向用户澄清，禁止猜测后查数。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                    },
                },
                "required": ["question", "options"],
            },
        ),
        ToolSpec(
            name="search_episodic_memory",
            description="检索当前商家历史分析记忆（情景记忆），用于「之前/上次/历史」类提问。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "shop_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                },
                "required": ["query", "shop_id"],
            },
        ),
        ToolSpec(
            name="search_metric_knowledge",
            description="检索平台公共指标口径/安全阈值等 RAG 知识，禁止写入商家私有数据。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                },
                "required": ["query"],
            },
        ),
        ToolSpec(
            name="run_product_pipeline",
            description="对店铺商品做抽取→分类→校验（规则优先；灰色样本标记 needs_llm）。用于质检/脏数据。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {"shop_id": {"type": "string"}},
                "required": ["shop_id"],
            },
        ),
        ToolSpec(
            name="detect_price_anomaly",
            description="按类目分位数/IQR 检测价格异常。数字由统计方法给出，禁止模型心算。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {"shop_id": {"type": "string"}},
                "required": ["shop_id"],
            },
            emits_metrics=("price_anomaly_count",),
        ),
        ToolSpec(
            name="flag_invalid_orders",
            description="用规则识别无效/脏订单（取消、退款、0 元已支付、重复单号、非法手机号）。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                },
                "required": ["shop_id"],
            },
            emits_metrics=("invalid_order_count",),
        ),
        ToolSpec(
            name="forecast_sales",
            description="窗口均值 × 演示星期权重预测未来几天销售额。不是训练好的深度学习模型。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string"},
                    "horizon": {"type": "integer", "minimum": 1, "maximum": 14, "default": 7},
                },
                "required": ["shop_id"],
            },
            emits_metrics=("forecast_baseline_gmv",),
        ),
        ToolSpec(
            name="run_workflow",
            description="执行命名工作流：product_qc / ops_diagnosis / ad_diagnosis。多步可观测。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string"},
                    "workflow": {
                        "type": "string",
                        "enum": ["product_qc", "ops_diagnosis", "ad_diagnosis"],
                    },
                },
                "required": ["shop_id", "workflow"],
            },
        ),
        ToolSpec(
            name="query_ad_performance",
            description="查询演示广告投放花费、GMV、ROI 与亏损计划。数字来自广告表聚合，禁止心算。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                },
                "required": ["shop_id"],
            },
            emits_metrics=("ad_spend", "ad_roi"),
        ),
        ToolSpec(
            name="run_ocr_check",
            description="对商品主图跑假 OCR（查表），再与标题做图文一致校验。不是真实视觉模型。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {"shop_id": {"type": "string"}},
                "required": ["shop_id"],
            },
        ),
        ToolSpec(
            name="run_alert_scan",
            description="按阈值扫描预警（低 ROI、高退款率、图文不符）并写入预警列表。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {"shop_id": {"type": "string"}},
                "required": ["shop_id"],
            },
        ),
        ToolSpec(
            name="list_alerts",
            description="列出当前店铺预警事件（演示数据 + 扫描结果）。",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shop_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["open", "acked", "all"], "default": "open"},
                },
                "required": ["shop_id"],
            },
        ),
    ]
