/**
 * API 客户端
 */
import axios, { type AxiosInstance } from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || '/api'

const ACCESS_TOKEN_KEY = 'auth.accessToken'
const REFRESH_TOKEN_KEY = 'auth.refreshToken'
const USER_KEY = 'auth.user'

export interface AuthUser {
    id: string
    email: string
    username?: string | null
    role: 'admin' | 'user'
    tenant_id?: string | null
    tenant_role?: 'owner' | 'admin' | 'member' | null
    status: string
}

export interface TenantOption {
    id: string
    name: string
    role: 'owner' | 'admin' | 'member'
}

export interface TenantListResponse {
    items: Array<TenantOption & { status?: string }>
    active_tenant_id?: string
}

export interface TenantMemberItem {
    tenant_id: string
    user_id: string
    name: string
    email?: string | null
    role: 'owner' | 'admin' | 'member'
    status: 'active' | 'inactive'
    created_at?: string
}

export interface TenantMemberListResponse {
    tenant_id: string
    items: TenantMemberItem[]
}

export interface LimitsResponse {
    tenant_id: string
    user_id?: string
    rate_limits: {
        read: string
        write: string
        execute: string
        user_read: string
        user_write: string
        user_execute: string
        tenant_concurrency_limit: number
        user_concurrency_limit: number
        fail_mode: string
    }
    quota: {
        monthly_token_quota: number
        enabled: boolean
    }
}

export interface QuotaResponse {
    tenant_id: string
    period: string
    enabled: boolean
    monthly_token_quota: number
    used_tokens: number
    remaining_tokens: number
    prompt_tokens: number
    completion_tokens: number
    request_count: number
}

export interface SecretItem {
    id: string
    tenant_id: string
    owner_user_id?: string | null
    scope: 'user' | 'tenant'
    name: string
    provider?: string | null
    status: 'active' | 'disabled' | 'deleted'
    current_version: number
    updated_at?: string
}

export interface AuthAuditEvent {
    event_id: string
    event_time: string
    event_type: string
    request_id?: string | null
    user_id?: string | null
    email?: string | null
    actor_type?: string | null
    actor_id?: string | null
    ip_addr?: string | null
    user_agent?: string | null
    result?: string | null
    reason_code?: string | null
    payload: Record<string, any>
}

export interface PaginatedAuthAuditResponse {
    items: AuthAuditEvent[]
    total: number
    limit: number
    offset: number
}

export interface AuthAuditOverview {
    window_hours: number
    total_events: number
    login_success: number
    login_failed: number
    login_success_rate: number
    unique_user_count: number
    unique_ip_count: number
    top_failure_reasons: Record<string, number>
}

export interface GuardrailPolicyResponse {
    tenant_id: string
    enabled: boolean
    mode: 'monitor' | 'enforce' | string
    config: Record<string, any>
    created_at?: string
    updated_at?: string
}

export interface CacheStatsResponse {
    tenant_id: string
    total_entries: number
    total_hits: number
}

export interface CacheEntryItem {
    id: string
    tenant_id: string
    namespace: string
    prompt_hash: string
    response: string
    metadata: Record<string, any>
    created_at?: string
    updated_at?: string
}

export interface CacheEntryListResponse {
    items: CacheEntryItem[]
    total: number
    limit: number
    offset: number
}

export interface CacheInvalidateResponse {
    tenant_id: string
    namespace?: string | null
    deleted: number
}

const ACTIVE_TENANT_KEY = 'auth.activeTenantId'

function readAccessToken(): string {
    return window.localStorage.getItem(ACCESS_TOKEN_KEY) || ''
}

function readRefreshToken(): string {
    return window.localStorage.getItem(REFRESH_TOKEN_KEY) || ''
}

function writeTokens(accessToken: string, refreshToken: string) {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
    window.localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
}

function clearTokens() {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    window.localStorage.removeItem(REFRESH_TOKEN_KEY)
    window.localStorage.removeItem(USER_KEY)
    window.localStorage.removeItem(ACTIVE_TENANT_KEY)
}

function writeUser(user: AuthUser | null) {
    if (!user) {
        window.localStorage.removeItem(USER_KEY)
        return
    }
    window.localStorage.setItem(USER_KEY, JSON.stringify(user))
}

function readUser(): AuthUser | null {
    const raw = window.localStorage.getItem(USER_KEY)
    if (!raw) return null
    try {
        return JSON.parse(raw) as AuthUser
    } catch {
        return null
    }
}

function readActiveTenantId(): string {
    return window.localStorage.getItem(ACTIVE_TENANT_KEY) || ''
}

function writeActiveTenantId(tenantId: string) {
    if (!tenantId) {
        window.localStorage.removeItem(ACTIVE_TENANT_KEY)
        return
    }
    window.localStorage.setItem(ACTIVE_TENANT_KEY, tenantId)
}

export interface CreateSessionRequest {
    title?: string
}

export interface ChatRequest {
    message: string
    config?: Record<string, unknown>
}

export interface FeedbackRequest {
    decision: 'approve' | 'reject'
    message?: string
}

export interface AuditRunItem {
    request_id: string
    time: string
    root_agent_name?: string | null
    status: string
    duration_seconds?: number | null
    initiator?: string | null
    conversation_id?: string | null
    session_id?: string | null
    llm_calls_count: number
    tool_calls_count: number
    failures_count: number
    interrupts_count: number
    action_type: 'llm' | 'tool' | 'chain' | 'interrupt' | 'job'
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    token_source: 'exact' | 'estimated' | 'none'
}

export interface AuditRunsResponse {
    items: AuditRunItem[]
    total: number
    limit: number
    offset: number
}

export interface AuditOverview {
    window_hours: number
    total_requests: number
    avg_latency_ms: number
    total_tokens: number
    succeeded_requests: number
    failed_requests: number
    interrupted_requests: number
    running_requests: number
}

export interface AuditRunDetail {
    run: AuditRunItem
    failures: Array<{
        event_id: string
        time: string
        type: string
        component?: string | null
        message: string
        severity: string
        payload?: Record<string, any>
        span_id?: string | null
    }>
    spans: Array<{
        span_id: string
        parent_span_id?: string | null
        type: string
        name: string
        status: string
        duration?: number | null
        started_at?: string | null
        ended_at?: string | null
        agent_name?: string | null
        subagent_kind?: string | null
        node_name?: string | null
        meta?: Record<string, any>
    }>
    recent_events: Array<{
        event_id: string
        time: string
        type: string
        component?: string | null
        message: string
        severity: string
        payload?: Record<string, any>
        span_id?: string | null
    }>
    insights?: {
        primary_action?: string
        model_name?: string | null
        prompt_tokens?: number
        completion_tokens?: number
        total_tokens?: number
        token_source?: string
        estimated_cost_usd?: number | null
        input_preview?: string | null
        output_preview?: string | null
        latency_breakdown_ms?: {
            network?: number
            inference?: number
            thinking?: number
            total?: number
        }
        stats?: {
            ttft_ms?: number | null
            throughput_tps?: number | null
            context_window_utilization_pct?: number
        }
        resource_details?: Array<{
            resource: string
            type?: string
            status?: string
            duration_ms?: number
        }>
        metadata?: {
            environment?: string | null
            initiator?: string | null
            conversation_id?: string | null
            thread_id?: string | null
            tags?: string[]
        }
    }
}

class ApiClient {
    private baseUrl: string
    public http: AxiosInstance
    private refreshPromise: Promise<void> | null = null

    constructor(baseUrl: string = API_BASE) {
        this.baseUrl = baseUrl
        this.http = axios.create({
            baseURL: baseUrl,
            headers: {
                'Content-Type': 'application/json',
            }
        })

        this.http.interceptors.request.use((config) => {
            const token = readAccessToken()
            if (token) {
                config.headers = config.headers || {}
                config.headers.Authorization = `Bearer ${token}`
            }
            const tenantId = readActiveTenantId()
            if (tenantId) {
                config.headers = config.headers || {}
                config.headers['X-Tenant-Id'] = tenantId
            }
            return config
        })

        this.http.interceptors.response.use(
            response => response.data,
            async (error) => {
                const status = error?.response?.status
                const originalRequest = error?.config || {}
                const isRefreshPath = String(originalRequest.url || '').includes('/auth/refresh')
                const canRetry = status === 401 && !originalRequest.__retry && !isRefreshPath && !!readRefreshToken()

                if (canRetry) {
                    originalRequest.__retry = true
                    try {
                        await this.refreshAccessToken()
                        originalRequest.headers = originalRequest.headers || {}
                        originalRequest.headers.Authorization = `Bearer ${readAccessToken()}`
                        return this.http.request(originalRequest)
                    } catch {
                        this.clearAuth()
                    }
                }

                return Promise.reject(error)
            }
        )
    }

    isAuthenticated(): boolean {
        return !!readAccessToken()
    }

    getStoredUser(): AuthUser | null {
        return readUser()
    }

    getActiveTenantId(): string {
        return readActiveTenantId()
    }

    setActiveTenantId(tenantId: string) {
        writeActiveTenantId(tenantId)
    }

    clearAuth() {
        clearTokens()
    }

    async refreshAccessToken(): Promise<void> {
        if (this.refreshPromise) return this.refreshPromise

        const refreshToken = readRefreshToken()
        if (!refreshToken) throw new Error('No refresh token')

        this.refreshPromise = (async () => {
            const result = await axios.post<{ access_token: string; refresh_token: string }>(
                `${this.baseUrl}/auth/refresh`,
                { refresh_token: refreshToken },
                { headers: { 'Content-Type': 'application/json' } }
            )
            writeTokens(result.data.access_token, result.data.refresh_token)
        })().finally(() => {
            this.refreshPromise = null
        })

        return this.refreshPromise
    }

    async bootstrapAuth(): Promise<AuthUser | null> {
        if (!this.isAuthenticated()) return null
        try {
            const user = await this.getMe()
            return user
        } catch {
            try {
                await this.refreshAccessToken()
                return await this.getMe()
            } catch {
                this.clearAuth()
                return null
            }
        }
    }

    async login(email: string, password: string): Promise<AuthUser> {
        const res = await this.http.post<any, { access_token: string; refresh_token: string }>('/auth/login', { email, password })
        writeTokens(res.access_token, res.refresh_token)
        const me = await this.getMe()
        writeUser(me)
        return me
    }

    async logout(): Promise<void> {
        const refreshToken = readRefreshToken()
        if (refreshToken) {
            try {
                await this.http.post('/auth/logout', { refresh_token: refreshToken })
            } catch {
                // ignore logout backend errors
            }
        }
        this.clearAuth()
    }

    async getMe(): Promise<AuthUser> {
        const user = await this.http.get<any, AuthUser>('/auth/me')
        writeUser(user)
        if (user?.tenant_id && !readActiveTenantId()) {
            writeActiveTenantId(user.tenant_id)
        }
        return user
    }

    async listMyTenants(): Promise<TenantListResponse> {
        const res = await this.http.get<any, TenantListResponse>('/auth/tenants')
        if (res?.active_tenant_id) {
            const active = readActiveTenantId()
            if (!active) writeActiveTenantId(res.active_tenant_id)
        }
        return res
    }

    async listTenantMembers(tenantId: string): Promise<TenantMemberListResponse> {
        return this.http.get(`/auth/tenants/${tenantId}/members`)
    }

    async inviteTenantMember(
        tenantId: string,
        input: { user_id?: string; email?: string; role?: 'owner' | 'admin' | 'member' },
    ): Promise<TenantMemberItem> {
        return this.http.post(`/auth/tenants/${tenantId}/members/invite`, input)
    }

    async updateTenantMemberRole(
        tenantId: string,
        memberUserId: string,
        role: 'owner' | 'admin' | 'member',
    ): Promise<TenantMemberItem> {
        return this.http.patch(`/auth/tenants/${tenantId}/members/${memberUserId}`, { role })
    }

    async removeTenantMember(tenantId: string, memberUserId: string): Promise<{ removed: boolean }> {
        return this.http.delete(`/auth/tenants/${tenantId}/members/${memberUserId}`)
    }

    async register(input: { email: string; password: string; username?: string | null }): Promise<AuthUser> {
        const user = await this.http.post<any, AuthUser>('/auth/register', input)
        return user
    }

    async createApiKey(name: string): Promise<any> {
        return this.http.post('/auth/api-keys', { name })
    }

    async listApiKeys(): Promise<any> {
        return this.http.get('/auth/api-keys')
    }

    async revokeApiKey(keyId: string): Promise<any> {
        return this.http.delete(`/auth/api-keys/${keyId}`)
    }

    async getMyLimits(): Promise<LimitsResponse> {
        return this.http.get('/limits/me')
    }

    async getMyQuota(): Promise<QuotaResponse> {
        return this.http.get('/quota/me')
    }

    async getMyGuardrails(): Promise<GuardrailPolicyResponse> {
        return this.http.get('/guardrails/me')
    }

    async getCacheStatsMe(): Promise<CacheStatsResponse> {
        return this.http.get('/cache/me/stats')
    }

    async listTenantCacheEntries(
        tenantId: string,
        params?: { limit?: number; offset?: number; namespace?: string }
    ): Promise<CacheEntryListResponse> {
        return this.http.get(`/admin/tenants/${tenantId}/cache/entries`, { params })
    }

    async invalidateTenantCache(
        tenantId: string,
        payload?: { namespace?: string }
    ): Promise<CacheInvalidateResponse> {
        return this.http.post(`/admin/tenants/${tenantId}/cache/invalidate`, payload || {})
    }

    async getTenantLimits(tenantId: string): Promise<LimitsResponse> {
        return this.http.get(`/limits/admin/tenants/${tenantId}`)
    }

    async updateTenantLimits(tenantId: string, patch: Record<string, any>): Promise<LimitsResponse> {
        return this.http.put(`/limits/admin/tenants/${tenantId}`, patch)
    }

    async getTenantQuota(tenantId: string): Promise<QuotaResponse> {
        return this.http.get(`/limits/admin/tenants/${tenantId}/quota`)
    }

    async updateTenantQuota(tenantId: string, patch: { monthly_token_quota?: number; enabled?: boolean }): Promise<QuotaResponse> {
        return this.http.put(`/limits/admin/tenants/${tenantId}/quota`, patch)
    }

    async listSecrets(scope?: 'user' | 'tenant'): Promise<{ items: SecretItem[] }> {
        return this.http.get('/secrets/', { params: scope ? { scope } : undefined })
    }

    async createSecret(input: { name: string; value: string; scope: 'user' | 'tenant'; provider?: string }): Promise<SecretItem> {
        return this.http.post('/secrets/', input)
    }

    async getSecret(secretId: string): Promise<SecretItem> {
        return this.http.get(`/secrets/${secretId}`)
    }

    async rotateSecret(secretId: string, value: string): Promise<SecretItem> {
        return this.http.post(`/secrets/${secretId}/rotate`, { value })
    }

    async disableSecret(secretId: string): Promise<SecretItem> {
        return this.http.post(`/secrets/${secretId}/disable`)
    }

    async enableSecret(secretId: string): Promise<SecretItem> {
        return this.http.post(`/secrets/${secretId}/enable`)
    }

    async deleteSecret(secretId: string): Promise<SecretItem> {
        return this.http.delete(`/secrets/${secretId}`)
    }

    async adminListTenantSecrets(tenantId: string): Promise<{ items: SecretItem[] }> {
        return this.http.get(`/secrets/admin/tenants/${tenantId}`)
    }

    async adminCreateTenantSecret(tenantId: string, input: { name: string; value: string; provider?: string }): Promise<SecretItem> {
        return this.http.post(`/secrets/admin/tenants/${tenantId}`, { ...input, scope: 'tenant' })
    }

    async reencryptTenantSecrets(tenantId: string): Promise<{ tenant_id: string; queued: boolean; job_id?: string }> {
        return this.http.post(`/secrets/admin/tenants/${tenantId}/reencrypt`, {})
    }

    private async fetchWithAuth(url: string, init: RequestInit = {}, retry = true): Promise<Response> {
        const headers = new Headers(init.headers || {})
        headers.set('Content-Type', headers.get('Content-Type') || 'application/json')
        const token = readAccessToken()
        if (token) headers.set('Authorization', `Bearer ${token}`)

        let response = await fetch(url, { ...init, headers })
        if (response.status === 401 && retry && !!readRefreshToken()) {
            try {
                await this.refreshAccessToken()
                const retriedHeaders = new Headers(init.headers || {})
                retriedHeaders.set('Content-Type', retriedHeaders.get('Content-Type') || 'application/json')
                const refreshedToken = readAccessToken()
                if (refreshedToken) retriedHeaders.set('Authorization', `Bearer ${refreshedToken}`)
                response = await fetch(url, { ...init, headers: retriedHeaders })
            } catch {
                this.clearAuth()
            }
        }
        return response
    }

    // Agent 操作
    async listAgents(): Promise<any[]> {
        return this.http.get('/agents/')
    }

    async getAgent(agentId: string): Promise<any> {
        return this.http.get(`/agents/${agentId}`)
    }

    async createAgent(config: any): Promise<any> {
        return this.http.post('/agents/', config)
    }

    async updateAgent(agentId: string, config: any): Promise<any> {
        return this.http.put(`/agents/${agentId}`, config)
    }

    async deleteAgent(agentId: string): Promise<void> {
        return this.http.delete(`/agents/${agentId}`)
    }

    async getAgentSchema(agentId: string): Promise<any> {
        return this.http.get(`/agents/${agentId}/config-schema`)
    }

    // Agent Version 操作
    async listAgentVersions(agentId: string, params?: { status?: string; limit?: number; offset?: number }): Promise<any[]> {
        return this.http.get(`/agents/${agentId}/versions/`, { params })
    }

    async getAgentVersion(agentId: string, version: number): Promise<any> {
        return this.http.get(`/agents/${agentId}/versions/${version}`)
    }

    async createAgentDraft(agentId: string, body: { config: Record<string, any>; change_summary?: string; base_version?: number }): Promise<any> {
        return this.http.post(`/agents/${agentId}/versions/`, body)
    }

    async updateAgentDraft(agentId: string, version: number, body: { config?: Record<string, any>; change_summary?: string }): Promise<any> {
        return this.http.put(`/agents/${agentId}/versions/${version}`, body)
    }

    async publishAgentVersion(agentId: string, version: number): Promise<any> {
        return this.http.post(`/agents/${agentId}/versions/${version}/publish`)
    }

    async rollbackAgentVersion(agentId: string, version: number): Promise<any> {
        return this.http.post(`/agents/${agentId}/versions/${version}/rollback`)
    }

    async diffAgentVersions(agentId: string, v1: number, v2: number): Promise<any> {
        return this.http.get(`/agents/${agentId}/versions/${v1}/diff/${v2}`)
    }

    // Session 操作
    async createSession(title?: string, agentId?: string): Promise<any> {
        return this.http.post('/sessions/', {
            title: title || '新对话',
            agent_id: agentId
        })
    }

    async listSessions(limit = 50): Promise<any> {
        return this.http.get('/sessions/', { params: { limit } })
    }

    async getSession(sessionId: string): Promise<any> {
        return this.http.get(`/sessions/${sessionId}`)
    }

    async deleteSession(sessionId: string): Promise<void> {
        return this.http.delete(`/sessions/${sessionId}`)
    }

    // 流式对话 - Fetch is better for streams
    streamChat(
        sessionId: string,
        message: string,
        onEvent: (event: string, data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await this.fetchWithAuth(`${this.baseUrl}/sessions/${sessionId}/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message }),
                    signal: controller.signal,
                })

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`)
                }

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('event:')) {
                            // 下一行应该是 data
                            continue
                        }
                        if (line.startsWith('data:')) {
                            try {
                                const data = JSON.parse(line.substring(5).trim())
                                onEvent(data.event || 'unknown', data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()

        return () => controller.abort()
    }

    // HITL Resume - Streaming
    resumeChat(
        sessionId: string,
        request: { decision: string, feedback: string },
        onEvent: (event: string, data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await this.fetchWithAuth(`${this.baseUrl}/sessions/${sessionId}/resume`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(request),
                    signal: controller.signal,
                })

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`)
                }

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('data:')) {
                            try {
                                const jsonStr = line.substring(5).trim()
                                if (!jsonStr) continue
                                const data = JSON.parse(jsonStr)
                                // SSE data usually array [msg, meta] or simple object {type: ...}
                                // Dispatch as event 'message' or use data.type
                                const eventType = Array.isArray(data) ? 'message' : (data.type || 'unknown')
                                onEvent(eventType, data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()

        return () => controller.abort()
    }

    async getState(sessionId: string): Promise<any> {
        return this.http.get(`/sessions/${sessionId}/state`)
    }

    // Async Task 操作
    async executeTask(sessionId: string, message: string, config?: any): Promise<any> {
        return this.http.post(`/tasks/sessions/${sessionId}/execute`, { message, config })
    }

    async getTask(taskId: string): Promise<any> {
        return this.http.get(`/tasks/${taskId}`)
    }

    async cancelTask(taskId: string): Promise<any> {
        return this.http.post(`/tasks/${taskId}/cancel`)
    }

    async resumeTask(taskId: string, decision: 'approve' | 'reject', feedback: string = ''): Promise<any> {
        return this.http.post(`/tasks/${taskId}/resume`, { decision, feedback })
    }

    async listSessionTasks(sessionId: string, params?: { status?: string; limit?: number }): Promise<any> {
        return this.http.get(`/tasks/sessions/${sessionId}`, { params })
    }

    streamSessionTasks(
        sessionId: string,
        onEvent: (data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await this.fetchWithAuth(`${this.baseUrl}/tasks/sessions/${sessionId}/stream`, {
                    signal: controller.signal,
                })

                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('data:')) {
                            try {
                                const jsonStr = line.substring(5).trim()
                                if (!jsonStr) continue
                                const data = JSON.parse(jsonStr)
                                onEvent(data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()
        return () => controller.abort()
    }

    // Audit API
    async listAuditRuns(params: {
        limit?: number;
        offset?: number;
        status?: string;
        agent?: string;
        action?: string;
        q?: string;
        start_date?: string;
        end_date?: string;
    } = {}): Promise<AuditRunsResponse> {
        return this.http.get('/audit/runs', { params: { limit: 50, ...params } })
    }

    async getAuditOverview(params: { window_hours?: number; agent?: string } = {}): Promise<AuditOverview> {
        return this.http.get('/audit/overview', { params })
    }

    async getAuditRunSummary(runId: string): Promise<AuditRunDetail> {
        return this.http.get(`/audit/runs/${runId}/summary`)
    }

    async listAuthAuditEvents(params: {
        limit?: number
        offset?: number
        event_type?: string
        user_id?: string
        email?: string
        ip_addr?: string
        result?: string
        start_date?: string
        end_date?: string
    } = {}): Promise<PaginatedAuthAuditResponse> {
        return this.http.get('/audit/auth/events', { params: { limit: 50, ...params } })
    }

    async getAuthAuditOverview(params: { window_hours?: number; user_id?: string } = {}): Promise<AuthAuditOverview> {
        return this.http.get('/audit/auth/overview', { params })
    }

    // RAG (via agent-api /rag gateway)
    async listKnowledgeBases(): Promise<{ items: any[] }> {
        return this.http.get('/rag/knowledge-bases')
    }

    async createKnowledgeBase(input: {
        name: string
        description?: string
        chunk_size?: number
        chunk_overlap?: number
        cleaning_rules?: Record<string, any>
    }): Promise<any> {
        return this.http.post('/rag/knowledge-bases', input)
    }

    async getKnowledgeBase(kbId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}`)
    }

    async updateKnowledgeBase(kbId: number, patch: Record<string, any>): Promise<any> {
        return this.http.put(`/rag/knowledge-bases/${kbId}`, patch)
    }

    async deleteKnowledgeBase(kbId: number): Promise<any> {
        return this.http.delete(`/rag/knowledge-bases/${kbId}`)
    }

    async getKnowledgeBaseStats(kbId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/stats`)
    }

    async listKnowledgeBaseDocuments(kbId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/documents`)
    }

    async deleteKnowledgeBaseDocument(kbId: number, docId: number): Promise<any> {
        return this.http.delete(`/rag/knowledge-bases/${kbId}/documents/${docId}`)
    }

    async uploadKnowledgeBaseDocument(kbId: number, file: File): Promise<any> {
        const form = new FormData()
        form.append('file', file)
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/upload`, form, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
    }

    async importKnowledgeBaseUrl(kbId: number, url: string): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/import-url`, {
            url,
            knowledge_base_id: kbId,
        })
    }

    async reindexDocument(kbId: number, docId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/${docId}/reindex`, {})
    }

    async listDocumentChunks(
        kbId: number,
        docId: number,
        params?: { offset?: number; limit?: number; include_parents?: boolean }
    ): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/documents/${docId}/chunks`, { params })
    }

    async getDocumentOutline(kbId: number, docId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/documents/${docId}/outline`)
    }

    async previewDocumentChunks(
        kbId: number,
        docId: number,
        input: { chunk_size?: number; chunk_overlap?: number; cleaning_rules?: Record<string, any>; limit?: number }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/documents/${docId}/preview-chunks`, input)
    }

    async rebuildKnowledgeBaseVectors(kbId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/rebuild-vectors`, {})
    }

    async buildKnowledgeBaseGraph(kbId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/build-graph`, {})
    }

    async ragRetrieve(input: { query: string; knowledge_base_id?: number; top_k?: number }): Promise<any> {
        return this.http.post('/rag/retrieve', input)
    }

    async ragGraphRetrieve(input: { query: string; knowledge_base_id?: number; top_k?: number }): Promise<any> {
        return this.http.post('/rag/graph/retrieve', input)
    }

    async ragEvaluate(input: { question: string; answer: string; contexts?: string[] }): Promise<any> {
        return this.http.post('/rag/evaluate', input)
    }

    // RAG Eval (Datasets / Benchmarks)
    async listEvalDatasets(kbId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/datasets`)
    }

    async exportAllEvalDatasets(kbId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/datasets/export`)
    }

    async createEvalDataset(kbId: number, input: { name: string; description?: string }): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets`, input)
    }

    async updateEvalDataset(kbId: number, datasetId: number, patch: Record<string, any>): Promise<any> {
        return this.http.put(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}`, patch)
    }

    async deleteEvalDataset(kbId: number, datasetId: number): Promise<any> {
        return this.http.delete(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}`)
    }

    async exportEvalDataset(kbId: number, datasetId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/export`)
    }

    async importEvalDataset(
        kbId: number,
        datasetId: number,
        input: {
            replace?: boolean
            cases: Array<{
                query: string
                expected_sources?: string[]
                expected_answer?: string
                notes?: string
                tags?: string[]
            }>
        }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/import`, input)
    }

    async listEvalCases(
        kbId: number,
        datasetId: number,
        params?: { q?: string; tag?: string; offset?: number; limit?: number }
    ): Promise<{ items: any[]; total?: number; offset?: number; limit?: number }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/cases`, { params })
    }

    async createEvalCase(
        kbId: number,
        datasetId: number,
        input: { query: string; expected_sources?: string[]; expected_answer?: string; notes?: string; tags?: string[] }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/cases`, input)
    }

    async bulkDeleteEvalCases(kbId: number, datasetId: number, caseIds: number[]): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/datasets/${datasetId}/cases/bulk-delete`, {
            case_ids: caseIds,
        })
    }

    async updateEvalCase(caseId: number, patch: Record<string, any>): Promise<any> {
        return this.http.put(`/rag/eval/cases/${caseId}`, patch)
    }

    async deleteEvalCase(caseId: number): Promise<any> {
        return this.http.delete(`/rag/eval/cases/${caseId}`)
    }

    async createBenchmarkRun(
        kbId: number,
        input: { dataset_id: number; mode: 'vector' | 'graph' | 'qa'; top_k: number }
    ): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs`, input)
    }

    async listBenchmarkRuns(kbId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs`)
    }

    async getBenchmarkRun(kbId: number, runId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}`)
    }

    async executeBenchmarkRun(kbId: number, runId: number): Promise<any> {
        return this.http.post(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}/execute`, {})
    }

    async listBenchmarkResults(kbId: number, runId: number): Promise<{ items: any[] }> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}/results`)
    }

    async exportBenchmarkRun(kbId: number, runId: number): Promise<any> {
        return this.http.get(`/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}/export`)
    }

    streamBenchmarkRun(
        kbId: number,
        runId: number,
        onEvent: (data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await this.fetchWithAuth(
                    `${this.baseUrl}/rag/knowledge-bases/${kbId}/eval/benchmarks/runs/${runId}/stream`,
                    {
                        signal: controller.signal,
                    }
                )

                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('data:')) {
                            try {
                                const jsonStr = line.substring(5).trim()
                                if (!jsonStr) continue
                                const data = JSON.parse(jsonStr)
                                onEvent(data)
                            } catch (e) {
                                // ignore malformed messages
                            }
                        }
                    }
                }
            } catch (error: any) {
                if (error?.name === 'AbortError') return
                onError?.(error)
            }
        }

        fetchStream()
        return () => controller.abort()
    }

    streamTask(
        taskId: string,
        onEvent: (data: any) => void,
        onError?: (error: Error) => void
    ): () => void {
        const controller = new AbortController()

        const fetchStream = async () => {
            try {
                const response = await this.fetchWithAuth(`${this.baseUrl}/tasks/${taskId}/stream`, {
                    signal: controller.signal,
                })

                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)

                const reader = response.body?.getReader()
                if (!reader) throw new Error('No response body')

                const decoder = new TextDecoder()
                let buffer = ''

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        if (line.startsWith('data:')) {
                            try {
                                const jsonStr = line.substring(5).trim()
                                if (!jsonStr) continue
                                const data = JSON.parse(jsonStr)
                                onEvent(data)
                            } catch (e) {
                                console.warn('Failed to parse SSE data:', line)
                            }
                        }
                    }
                }
            } catch (error) {
                if ((error as Error).name !== 'AbortError') {
                    onError?.(error as Error)
                }
            }
        }

        fetchStream()
        return () => controller.abort()
    }

    // ─── Prompt Management ───────────────────────────────────────────

    async listPrompts(params?: { category?: string; key?: string; limit?: number; offset?: number }): Promise<any> {
        return this.http.get('/prompts', { params })
    }

    async getPrompt(templateId: string): Promise<any> {
        return this.http.get(`/prompts/${templateId}`)
    }

    async createPrompt(input: { key: string; name: string; description?: string; category?: string; content?: string; variables_schema?: Record<string, any> }): Promise<any> {
        return this.http.post('/prompts', input)
    }

    async updatePrompt(templateId: string, patch: { name?: string; description?: string; category?: string }): Promise<any> {
        return this.http.put(`/prompts/${templateId}`, patch)
    }

    async listPromptVersions(templateId: string, params?: { status?: string }): Promise<any> {
        return this.http.get(`/prompts/${templateId}/versions`, { params })
    }

    async createPromptDraft(templateId: string, input: { content: string; variables_schema?: Record<string, any>; change_summary?: string; base_version?: number }): Promise<any> {
        return this.http.post(`/prompts/${templateId}/versions`, input)
    }

    async updatePromptDraft(templateId: string, version: number, input: { content?: string; variables_schema?: Record<string, any>; change_summary?: string }): Promise<any> {
        return this.http.put(`/prompts/${templateId}/versions/${version}`, input)
    }

    async publishPromptVersion(templateId: string, version: number): Promise<any> {
        return this.http.post(`/prompts/${templateId}/versions/${version}/publish`, {})
    }

    async rollbackPromptVersion(templateId: string, version: number): Promise<any> {
        return this.http.post(`/prompts/${templateId}/versions/${version}/rollback`, {})
    }

    async previewPrompt(templateId: string, input: { content?: string; variables?: Record<string, string>; version?: number }): Promise<any> {
        return this.http.post(`/prompts/${templateId}/preview`, input)
    }

    async createPromptABTest(templateId: string, input: {
        name: string
        variant_a_version: number
        variant_b_version: number
        traffic_split: number
    }): Promise<any> {
        return this.http.post(`/prompts/${templateId}/ab-tests`, input)
    }

    async getPromptABTest(templateId: string, testId: string): Promise<any> {
        return this.http.get(`/prompts/${templateId}/ab-tests/${testId}`)
    }

    async completePromptABTest(templateId: string, testId: string, input: { winner_version?: number }): Promise<any> {
        return this.http.post(`/prompts/${templateId}/ab-tests/${testId}/complete`, input)
    }

    async listAgentEvalDatasets(agentId: string): Promise<any> {
        return this.http.get(`/agents/${agentId}/eval/datasets`)
    }

    async createAgentEvalDataset(agentId: string, input: { name: string; description?: string }): Promise<any> {
        return this.http.post(`/agents/${agentId}/eval/datasets`, input)
    }

    async listAgentEvalCases(agentId: string, datasetId: string, params?: { limit?: number; offset?: number }): Promise<any> {
        return this.http.get(`/agents/${agentId}/eval/datasets/${datasetId}/cases`, { params })
    }

    async importAgentEvalCases(agentId: string, datasetId: string, input: { cases: Array<Record<string, any>> }): Promise<any> {
        return this.http.post(`/agents/${agentId}/eval/datasets/${datasetId}/import`, input)
    }

    async createAgentEvalRun(agentId: string, input: { dataset_id: string; config?: Record<string, any> }): Promise<any> {
        return this.http.post(`/agents/${agentId}/eval/runs`, input)
    }

    async listAgentEvalRuns(agentId: string, params?: { limit?: number; offset?: number }): Promise<any> {
        return this.http.get(`/agents/${agentId}/eval/runs`, { params })
    }

    async getAgentEvalRun(agentId: string, runId: string): Promise<any> {
        return this.http.get(`/agents/${agentId}/eval/runs/${runId}`)
    }

    async listAgentEvalResults(agentId: string, runId: string, params?: { limit?: number; offset?: number }): Promise<any> {
        return this.http.get(`/agents/${agentId}/eval/runs/${runId}/results`, { params })
    }

    async compareAgentEvalRuns(agentId: string, runId1: string, runId2: string): Promise<any> {
        return this.http.get(`/agents/${agentId}/eval/runs/${runId1}/compare/${runId2}`)
    }
}

export const apiClient = new ApiClient()
export default apiClient
