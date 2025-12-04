import { http } from './http'

export interface AgentMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
}

export interface AgentControlParams {
  pipeline_name?: string | null
  node?: string | null
  model_uri?: string | null
  timeout_sec?: number | null
}

export interface AgentControlRequest {
  op: 'pipeline.delete' | 'pipeline.hotswap' | 'pipeline.drain'
  mode: 'plan' | 'execute'
  params: AgentControlParams
  confirm: boolean
}

export interface AgentInvokeRequest {
  messages: AgentMessage[]
  control?: AgentControlRequest | null
}

export interface AgentControlResult {
  op: string
  mode: 'plan' | 'execute'
  success: boolean
  plan?: any
  result?: any
  error?: string | null
}

export interface AgentInvokeResponse {
  message: AgentMessage
  raw_state?: any
  control_result?: AgentControlResult | null
  agent_data?: {
    status?: string
    steps?: any[]
  } | null
}

export interface AgentThreadSummary {
  thread_id: string
  last_user_message?: string | null
  last_assistant_message?: string | null
  last_control_op?: string | null
  last_control_mode?: string | null
  last_control_success?: boolean | null
  updated_at?: string | null
}

// DB / Excel 图表分析通用结构
export interface AgentChartResult {
  id: string
  title: string
  description?: string | null
  option: any
}

export interface DbChartRequest {
  session_id: string
  db_name?: string | null
  query: string
}

export interface DbChartResponse {
  used_db_name?: string | null
  charts: AgentChartResult[]
  insight?: string | null
}

export interface ExcelChartRequest {
  session_id: string
  file_id: string
  sheet_name?: string | null
  query: string
}

export interface ExcelChartResponse {
  used_sheet_name?: string | null
  charts: AgentChartResult[]
  insight?: string | null
}

// 通过 CP 代理到 Agent：/api/agent/threads/{thread_id}/invoke
export const agentApi = {
  async invokeThread(
    threadId: string,
    payload: AgentInvokeRequest,
  ): Promise<AgentInvokeResponse> {
    const path = `/api/agent/threads/${encodeURIComponent(threadId)}/invoke`
    return http.post<AgentInvokeResponse>(path, payload)
  },
  async listThreads(): Promise<AgentThreadSummary[]> {
    return http.get<AgentThreadSummary[]>('/api/agent/threads')
  },
  async getThreadSummary(threadId: string): Promise<AgentThreadSummary> {
    const path = `/api/agent/threads/${encodeURIComponent(threadId)}/summary`
    return http.get<AgentThreadSummary>(path)
  },

  // 数据库分析（SQL Agent）
  async dbChart(payload: DbChartRequest): Promise<DbChartResponse> {
    // DB/Excel 分析可能耗时较长，这里使用更大的超时时间（120s）
    if (typeof (http as any).postWithTimeout === 'function') {
      return (http as any).postWithTimeout('/api/agent/db/chart', payload, 120000)
    }
    return http.post<DbChartResponse>('/api/agent/db/chart', payload)
  },

  // Excel 分析
  async excelChart(payload: ExcelChartRequest): Promise<ExcelChartResponse> {
    if (typeof (http as any).postWithTimeout === 'function') {
      return (http as any).postWithTimeout('/api/agent/excel/chart', payload, 120000)
    }
    return http.post<ExcelChartResponse>('/api/agent/excel/chart', payload)
  },
}

const AGENT_ENABLED = (
  ((import.meta as any).env?.VITE_AGENT_ENABLED || '') as string
).toString() === '1'

export function isAgentEnabled(): boolean {
  return AGENT_ENABLED
}
