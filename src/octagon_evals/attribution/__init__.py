"""自动归因（agentic）：行为证据 + rubric + 分数 → 现象 / 根因 / 修改建议。

评分后的分析角色，非 scoring method。见 docs/attribution.md。
"""
from .service import AttributionService

__all__ = ["AttributionService"]
