"""Presentation adapter for DEM execution plans."""
from __future__ import annotations

import json


def format_raster_plan(plan: dict) -> str:
    inputs = plan.get("inputs", {})
    params = plan.get("parameters", {})
    risks = "\n".join(f"• {risk}" for risk in plan.get("risks", []))
    return (f"输入 DEM：{inputs.get('layer_name', '未指定')}（波段 {inputs.get('band', '?')}，"
            f"{inputs.get('width', '?')}×{inputs.get('height', '?')}，{inputs.get('crs', '未知 CRS')}）\n"
            f"参数：{json.dumps(params, ensure_ascii=False, default=str)}\n"
            f"输出：{plan.get('output_path', '未指定')}\n"
            f"影响：{plan.get('impact', '')}\n风险：\n{risks}")
