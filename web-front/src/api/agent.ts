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
}

const AGENT_ENABLED = (
  ((import.meta as any).env?.VITE_AGENT_ENABLED || '') as string
).toString() === '1'

export function isAgentEnabled(): boolean {
  return AGENT_ENABLED
}
