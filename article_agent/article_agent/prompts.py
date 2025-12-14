from __future__ import annotations


COMMON_CONSTRAINTS_ZH = """
【通用约束】

- 回答语言：默认使用简体中文。
- 严禁在输出中暴露你的思考过程、推理步骤或任何 <think>...</think> 内容。
- 严禁向用户解释你打算如何调用工具或内部执行流程，不要出现“首先我会……接下来我要……”之类的话。
- 当要求你输出 JSON 时：
  - 只能输出一个合法 JSON；
  - 严禁在 JSON 前后添加任何多余文字或注释；
  - 严禁多次输出多个 JSON。
""".strip()


__all__ = ["COMMON_CONSTRAINTS_ZH"]

