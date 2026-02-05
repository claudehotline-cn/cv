import { defineStore } from 'pinia'

export type AgentBuilderToolToggles = {
  web_search: boolean
  code_interpreter: boolean
  image_generation: boolean
}

export type AgentBuilderKnowledgeItem =
  | {
      id: string
      type: 'file'
      name: string
      sizeLabel: string
      status: 'ready' | 'processing'
      progress?: number
    }
  | {
      id: string
      type: 'url'
      url: string
      status: 'synced'
      metaLabel: string
    }

export type AgentBuilderDraft = {
  name: string
  description: string
  system_prompt: string
  avatar_data_url: string | null

  tools: AgentBuilderToolToggles
  openapi_schema_name: string
  openapi_schema_text: string

  website_source_input: string
  knowledge: AgentBuilderKnowledgeItem[]
}

const DEFAULT_SCHEMA = `openapi: "3.0.0"
info:
  version: "1.0.0"
  title: "Swagger Petstore"
  license:
    name: "MIT"
servers:
  - url: "http://petstore.swagger.io/v1"
paths:
  /pets:
    get:
      summary: "List all pets"
      operationId: "listPets"
      # Gets all pets from the system
`

export const useAgentBuilderStore = defineStore('agentBuilder', {
  state: (): { draft: AgentBuilderDraft } => ({
    draft: {
      name: 'Support Bot',
      description: 'Assists users with account inquiries and troubleshooting common issues.',
      system_prompt: '',
      avatar_data_url: null,
      tools: {
        web_search: true,
        code_interpreter: true,
        image_generation: false,
      },
      openapi_schema_name: 'petstore-v3.yaml',
      openapi_schema_text: DEFAULT_SCHEMA,
      website_source_input: 'https://example.com/docs',
      knowledge: [
        {
          id: 'k1',
          type: 'file',
          name: 'Product_Manual_v2.pdf',
          sizeLabel: '2.4 MB',
          status: 'ready',
        },
        {
          id: 'k2',
          type: 'file',
          name: 'company_policy_2024.txt',
          sizeLabel: '145 KB',
          status: 'processing',
          progress: 65,
        },
        {
          id: 'k3',
          type: 'url',
          url: 'https://help.acme.inc/api-docs',
          status: 'synced',
          metaLabel: 'Website • 45 pages indexed',
        },
      ],
    },
  }),
  actions: {
    reset() {
      this.$reset()
    },
    setAvatarFromFile(file: File) {
      return new Promise<void>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => {
          this.draft.avatar_data_url = String(reader.result || '') || null
          resolve()
        }
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(file)
      })
    },
    removeAvatar() {
      this.draft.avatar_data_url = null
    },
    addWebsiteSource() {
      const url = (this.draft.website_source_input || '').trim()
      if (!url) return
      this.draft.knowledge.unshift({
        id: `url_${Date.now()}`,
        type: 'url',
        url,
        status: 'synced',
        metaLabel: 'Website • queued for indexing',
      })
      this.draft.website_source_input = ''
    },
    removeKnowledge(id: string) {
      this.draft.knowledge = this.draft.knowledge.filter((k) => k.id !== id)
    },
  },
})
