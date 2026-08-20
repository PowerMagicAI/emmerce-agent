"""
Deterministic stub LLM for offline/CI.

Still goes through ToolSpec + orchestrator path (not old keyword Agent),
so architecture is exercised without an API key.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable

from emmerce_agent.application.ports import LLMMessage, LLMResponse, LLMToolCall
from emmerce_agent.domain.tools.specs import ToolSpec
from emmerce_agent.infrastructure.llm.base import BaseLLMAdapter


class StubLLMAdapter(BaseLLMAdapter):
    """Rule-based planner that emits schema-valid tool calls."""

    model_name = "stub-planner-v1"

    def get_model_name(self) -> str:
        return self.model_name

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSpec] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        task_text = self._latest_task(messages)
        all_user = "\n".join(m.content or "" for m in messages if m.role == "user")

        if messages and "请基于以上工具结果" in (messages[-1].content or ""):
            if self._needs_more_tools(task_text, messages):
                shop = self._extract_shop(all_user) or "shop_a1"
                return LLMResponse(
                    content=None,
                    tool_calls=[
                        self._call(
                            "export_report",
                            {
                                "filename": f"slow_moving_{shop}.xlsx",
                                "rows": [{"shop_id": shop, "note": "stub export"}],
                            },
                        )
                    ],
                    model=self.model_name,
                )
            return self._text(self._summarize(messages), on_delta)

        has_tool_out = any(m.role == "tool" for m in messages)
        if has_tool_out and not self._needs_more_tools(task_text, messages):
            return self._text(self._summarize(messages), on_delta)

        calls = self._plan(task_text, all_user, messages)
        if not calls:
            return self._text("请说明要查询的店铺与指标，例如「今日支付GMV」。", on_delta)
        return LLMResponse(content=None, tool_calls=calls, model=self.model_name)

    def _text(self, content: str, on_delta: Callable[[str], None] | None) -> LLMResponse:
        if on_delta and content:
            step = 12
            for i in range(0, len(content), step):
                on_delta(content[i : i + step])
        return LLMResponse(content=content, tool_calls=[], model=self.model_name)

    def _plan(self, text: str, all_user: str, messages: list[LLMMessage]) -> list[LLMToolCall]:
        shop = self._extract_shop(all_user) or "shop_a1"

        if any(k in text for k in ("对比", "环比", "同比")):
            return [
                self._call(
                    "compare_metric",
                    {
                        "shop_id": shop,
                        "metric_code": "gmv_pay",
                        "date_from_a": "2026-08-03",
                        "date_to_a": "2026-08-03",
                        "date_from_b": "2026-08-04",
                        "date_to_b": "2026-08-04",
                    },
                )
            ]

        if re.search(r"\d{1,2}\s*月", text) and any(k in text for k in ("分析", "滞销", "复盘")):
            if "口径:" not in text and "自然月" not in text and "历史" not in text and "之前" not in text:
                if not any(m.role == "tool" and m.name == "ask_clarification" for m in messages):
                    return [
                        self._call(
                            "ask_clarification",
                            {
                                "question": "「月份」如何统计？",
                                "options": ["自然月（含退款前支付）", "活动周期", "仅已完成订单"],
                            },
                        )
                    ]

        if any(k in text for k in ("历史", "之前", "上次")) and "滞销" in text:
            return [self._call("search_episodic_memory", {"query": text, "shop_id": shop, "limit": 3})]

        if "滞销" in text or "不动销" in text:
            months = self._months(text) or ["2026-07"]
            return [
                self._call("query_slow_moving", {"shop_id": shop, "month": m, "include_detail": False})
                for m in months[:2]
            ]

        if any(k in text for k in ("质检", "抽取", "分类", "校验", "脏数据")):
            if "诊断" in text or "经营" in text:
                return [self._call("run_workflow", {"shop_id": shop, "workflow": "ops_diagnosis"})]
            if "工作流" in text or "一整套" in text or "流水线" in text:
                return [self._call("run_workflow", {"shop_id": shop, "workflow": "product_qc"})]
            return [self._call("run_product_pipeline", {"shop_id": shop})]

        if any(k in text for k in ("投放诊断", "广告诊断", "ad_diagnosis")):
            return [self._call("run_workflow", {"shop_id": shop, "workflow": "ad_diagnosis"})]

        if any(k in text for k in ("经营诊断", "诊断店铺", "ops_diagnosis")):
            return [self._call("run_workflow", {"shop_id": shop, "workflow": "ops_diagnosis"})]

        if any(k in text for k in ("预警", "告警")):
            return [self._call("run_alert_scan", {"shop_id": shop})]

        if any(k in text for k in ("OCR", "ocr", "图文", "主图识别")):
            return [self._call("run_ocr_check", {"shop_id": shop})]

        if any(k in text for k in ("广告", "投放", "投产", "ROI", "roi")):
            return [self._call("query_ad_performance", {"shop_id": shop})]

        if any(k in text for k in ("价格异常", "异常价", "离谱价", "价格离谱")):
            return [self._call("detect_price_anomaly", {"shop_id": shop})]

        if any(k in text for k in ("无效订单", "刷单", "退款单", "假单", "脏订单")):
            return [self._call("flag_invalid_orders", {"shop_id": shop})]

        if any(k in text for k in ("销量预测", "销售预测", "预测GMV", "未来几天", "预测销售额", "预测")):
            return [self._call("forecast_sales", {"shop_id": shop, "horizon": 7})]

        if any(k in text for k in ("退款率", "退款比例")):
            return [self._call("query_metric", {"shop_id": shop, "metric_code": "refund_rate"})]

        if any(k in text for k in ("订单量", "订单数", "成交单数")):
            return [self._call("query_metric", {"shop_id": shop, "metric_code": "order_count"})]

        if any(k in text for k in ("GMV", "gmv", "成交额", "支付", "销售额", "营业额", "今日销量")):
            return [
                self._call("search_metric_knowledge", {"query": "支付GMV口径", "limit": 2}),
                self._call("query_metric", {"shop_id": shop, "metric_code": "gmv_pay"}),
            ]

        if "客单价" in text or "AOV" in text.upper():
            return [self._call("query_metric", {"shop_id": shop, "metric_code": "aov"})]

        return []

    def _latest_task(self, messages: list[LLMMessage]) -> str:
        user_turns = [m.content or "" for m in messages if m.role == "user"]
        if not user_turns:
            return ""
        text = user_turns[0]  # original task usually first user message in turn
        # Prefer the first non-final-instruction user message
        for content in user_turns:
            if "请基于以上工具结果" in content:
                continue
            text = content
            break
        if "[Task]" in text:
            text = text.split("[Task]", 1)[1]
            if "[Evidence]" in text:
                text = text.split("[Evidence]", 1)[0]
        return text.strip()

    def _needs_more_tools(self, text: str, messages: list[LLMMessage]) -> bool:
        if ("导出" in text or "Excel" in text.lower()) and not any(
            m.role == "tool" and m.name == "export_report" for m in messages
        ):
            if any(m.role == "tool" and m.name == "query_slow_moving" for m in messages):
                return True
        return False

    def _summarize(self, messages: list[LLMMessage]) -> str:
        facts = []
        for m in messages:
            if m.role != "tool" or not m.content:
                continue
            try:
                payload = json.loads(m.content)
            except json.JSONDecodeError:
                continue
            data = payload.get("data") or {}
            if "value" in data:
                facts.append(f"{data.get('metric_code')}={data.get('value')}{data.get('unit','')}")
            if "delta" in data and "value_a" in data:
                facts.append(
                    f"对比{data.get('metric_code')} {data.get('value_a')}→{data.get('value_b')} 差值{data.get('delta')}"
                )
            if "summary" in data:
                s = data["summary"]
                facts.append(f"滞销 {s.get('month')}: {s.get('slow_moving_count')} 个SKU")
            if "hits" in data and data["hits"]:
                facts.append(f"召回记忆/知识 {len(data['hits'])} 条")
            if "download_url" in data:
                facts.append("已生成导出文件")
            if "anomaly_count" in data:
                facts.append(f"价格异常 {data.get('anomaly_count')} 条")
            if "invalid_count" in data:
                facts.append(f"无效订单 {data.get('invalid_count')} 笔")
            if "baseline_gmv" in data:
                facts.append(f"预测基线GMV={data.get('baseline_gmv')}")
            if "stats" in data and isinstance(data["stats"], dict):
                s = data["stats"]
                facts.append(f"质检通过 {s.get('passed')}/{s.get('total')}，待LLM {s.get('needs_llm')}")
            if "workflow" in data:
                facts.append(f"工作流 {data.get('workflow')} 完成")
            if "campaigns" in data and "roi" in data:
                facts.append(f"广告花费={data.get('spend')} ROI={data.get('roi')} 亏损计划{data.get('losing_count')}")
            if "mismatch_count" in data:
                facts.append(f"图文不符 {data.get('mismatch_count')} 条")
            if "alerts" in data:
                facts.append(f"未处理预警 {data.get('open')} 条")
        if not facts:
            return "已完成处理。"
        return "根据工具查询结果：" + "；".join(facts) + "。建议结合库存安全阈值优先处理高库存低动销商品。"

    def _call(self, name: str, args: dict[str, Any]) -> LLMToolCall:
        return LLMToolCall(id=f"call_{uuid.uuid4().hex[:10]}", name=name, arguments=args)

    @staticmethod
    def _extract_shop(text: str) -> str | None:
        m = re.search(r"shop_id\s*[=：]\s*(shop_[a-z0-9]+)", text, re.I)
        if m:
            return m.group(1)
        for c in re.findall(r"\b(shop_[a-z0-9]+)\b", text):
            if c != "shop_id":
                return c
        return None

    @staticmethod
    def _months(text: str) -> list[str]:
        found = []
        for m in re.finditer(r"(?P<m>\d{1,2})\s*月", text):
            month = int(m.group("m"))
            found.append(f"2026-{month:02d}")
        return list(dict.fromkeys(found))
