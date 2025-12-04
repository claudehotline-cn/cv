## DB Agent（SQLDatabase + SQL Agent）调用示例

本例展示如何通过 HTTP 调用 Agent 服务的 `/v1/agent/db/chart` 接口，让 LLM 基于 MySQL 数据库自动生成 SQL、执行只读查询并返回可直接用于前端渲染的 ECharts 图表配置。

### 请求示例

```bash
curl -X POST http://localhost:18081/v1/agent/db/chart \
  -H "Content-Type: application/json" \
  -H "X-User-Id: demo-user" \
  -H "X-User-Role: admin" \
  -H "X-Tenant: tenant-a" \
  -d '{
    "session_id": "s-db-001",
    "db_name": "cv_cp",
    "query": "按月份统计订单金额和订单数，画一个双折线图，并给出结论"
  }'
```

### 响应结构示意

```json
{
  "used_db_name": "cv_cp",
  "charts": [
    {
      "id": "db_chart_1",
      "title": "2024 年各月订单金额与订单数",
      "description": "整体订单金额呈上升趋势，6 月出现峰值……",
      "option": {
        "title": { "text": "2024 年各月订单金额与订单数" },
        "dataset": {
          "source": [
            ["month", "order_amount", "order_count"],
            ["2024-01", 10000, 120],
            ["2024-02", 13000, 150]
          ]
        },
        "xAxis": { "type": "category" },
        "yAxis": { "type": "value" },
        "series": [
          { "type": "line", "name": "order_amount", "encode": { "x": "month", "y": "order_amount" } },
          { "type": "line", "name": "order_count", "encode": { "x": "month", "y": "order_count" } }
        ]
      }
    }
  ],
  "insight": "这里是基于聚合结果生成的整体分析结论……"
}
```

前端只需将 `charts[*].option` 传给 ECharts 的 `setOption` 即可完成图表渲染，`insight` 字段可直接展示为文字说明。

