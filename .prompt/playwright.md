你正在使用 Playwright MCP。除非我明确说明：
1) 不要调用 browser_snapshot。
2) 任何截图一律保存为文件且只返回文件路径；禁止内联 base64。
3) 仅使用这些工具：browser_navigate, browser_click, browser_type, browser_evaluate, browser_tabs。
4) 优先用 browser_evaluate 精确返回结构化 JSON（最多 10 条关键字段），禁止返回整页 HTML/DOM。
5) 只有我说要导出 PDF 时，才允许使用与 PDF 相关的能力。
6) 工具输出必须“最小充分”：不重复、不赘述、不粘贴大文本或二进制。
