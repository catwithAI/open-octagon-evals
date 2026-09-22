"""Judge 校准：RubricBench pairwise 轨道。

测量 harness，不进评分方法层。用官方协议（人工 gold + 官方原子 rubric +
论文 arXiv:2603.01562 Appendix F prompt）驱动配置的 judge，产出可信度报告。
见 docs/calibration.md。
"""
