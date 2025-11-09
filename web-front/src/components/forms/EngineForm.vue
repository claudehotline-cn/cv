<template>
  <div>
    <el-form v-if="fields.length" :model="model" label-width="180px" size="small">
      <template v-for="f in fields" :key="f.key">
        <el-form-item :label="labelText(f)" :prop="f.key">
          <component :is="inputOf(f)" v-model="model[f.key]" v-bind="inputProps(f)">
            <template v-if="f.type==='enum'">
              <el-option v-for="opt in (f.enum||[])" :key="String(opt)" :label="String(opt)" :value="opt" />
            </template>
          </component>
        </el-form-item>
      </template>
    </el-form>
    <div v-else class="empty">
      <el-empty description="正在读取引擎 Schema..." />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, defineExpose } from 'vue'
import { cp } from '@/api/cp'

type Field = { key:string; type:'bool'|'int'|'string'|'enum'; default?:any; help?:string; enum?:any[] }

const fields = ref<Field[]>([])
const model = ref<Record<string, any>>({})

function coerceDefault(f: Field) {
  if (f.default === undefined || f.default === null) return (f.type==='bool')? false : (f.type==='int'? 0 : '')
  if (f.type==='bool') return (String(f.default).toLowerCase() === 'true')
  if (f.type==='int') { const n = Number(f.default); return Number.isFinite(n)? n : 0 }
  return f.default
}

function inputOf(f: Field) {
  switch (f.type) {
    case 'bool': return 'el-switch'
    case 'int': return 'el-input-number'
    case 'enum': return 'el-select'
    default: return 'el-input'
  }
}
function inputProps(f: Field) {
  if (f.type==='int') return { step: 1 }
  if (f.type==='enum') return { filterable: true, clearable: true, style: 'width:240px' }
  return {}
}
function labelText(f: Field) {
  return f.help ? `${f.key}（${f.help}）` : f.key
}

async function loadSchema() {
  try {
    const r: any = await cp.getEngineSchema()
    const fs: Field[] = (r?.data?.fields || r?.fields) || []
    fields.value = fs
    const m: Record<string, any> = {}
    for (const f of fs) m[f.key] = coerceDefault(f)
    model.value = m
  } catch { fields.value = []; model.value = {} }
}

onMounted(loadSchema)

function getValues() { return { ...model.value } }
defineExpose({ getValues, reload: loadSchema })
</script>

<style scoped>
.empty{ padding: 12px }
</style>

