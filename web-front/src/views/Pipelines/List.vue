<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search, Plus, Star, StarFilled } from '@element-plus/icons-vue'
import { dataProvider } from '@/api/dataProvider'
import sample from '@/widgets/GraphEditor/samples/demo.json'

const router = useRouter()
const route = useRoute()
const rows = ref<any[]>([])
const q = ref('')
const loading = ref(false)
const status = ref<'All'|'Running'|'Stopped'|'Error'>('All')
const onlyStarred = ref(false)
const selection = ref<any[]>([])
const pageSize = ref(10)
const currentPage = ref(1)
const pageSizes = [10, 20, 50]

const favKey = 'pipeline_favorites'
function loadFav(): Set<string> { try{ return new Set(JSON.parse(localStorage.getItem(favKey)||'[]')) }catch{ return new Set() } }
function saveFav(v:Set<string>){ try{ localStorage.setItem(favKey, JSON.stringify(Array.from(v))) }catch{} }
const favorites = ref<Set<string>>(loadFav())

function decorate(items: any[]){
  return (items||[]).map((it, idx) => ({
    name: it.name || `pipeline_${idx+1}`,
    desc: it.desc || '-',
    running: typeof it.running==='boolean' ? it.running : Math.random() > 0.3,
    status: it.status || (Math.random() > 0.1 ? 'Running' : 'Stopped'),
    fps: it.fps ?? Math.round(20 + Math.random()*10),
    updatedAt: it.updatedAt || Date.now() - Math.floor(Math.random()*3600*1000)
  }))
}

async function load(){
  loading.value = true
  try {
    const data = await dataProvider.listPipelines();
    const items = (data as any)?.data ?? (data as any)?.items ?? data
    rows.value = decorate(items || [])
  }
  catch (e:any) { ElMessage.error(e?.message || 'Load failed') }
  finally { loading.value = false }
}

function create(){ router.push('/pipelines/editor') }

function toggleRun(row:any){ row.running = !row.running; row.status = row.running ? 'Running' : 'Stopped'; row.updatedAt = Date.now() }
function statusType(row:any){ return row.status==='Running' ? 'success' : row.status==='Error' ? 'danger' : 'info' }
function edit(row:any){ const key = `pipeline_draft_${row.name}`; try { const existing = localStorage.getItem(key); if (!existing) localStorage.setItem(key, JSON.stringify(sample)) } catch{}; router.push({ path:'/pipelines/editor', query:{ name: row.name } }) }
function removeRow(row:any){ rows.value = rows.value.filter(r => r !== row) }

function isFav(n:string){ return favorites.value.has(n) }
function toggleFav(n:string){ const set = new Set(favorites.value); if(set.has(n)) set.delete(n); else set.add(n); favorites.value = set; saveFav(set) }

function updateRouteQuery(partial: Record<string, any>) {
  const next = { ...route.query, ...partial }
  if (!next.q) delete next.q
  if (!next.status || next.status === 'All') delete next.status
  router.replace({ path: route.path, query: next })
}

function setStatus(next: 'All'|'Running'|'Stopped'|'Error'){
  status.value = next
  currentPage.value = 1
  savePref()
  updateRouteQuery({ status: next })
}

function onSelChange(arr:any[]){ selection.value = arr }
function startSelected(){ selection.value.forEach(r => { r.running = true; r.status='Running'; r.updatedAt=Date.now() }) }
function stopSelected(){ selection.value.forEach(r => { r.running = false; r.status='Stopped'; r.updatedAt=Date.now() }) }
function deleteSelected(){ rows.value = rows.value.filter(r => !selection.value.includes(r)); selection.value = [] }

const statusCounts = computed(()=>{
  const c = { All: rows.value.length, Running: 0, Stopped: 0, Error: 0 } as Record<'All'|'Running'|'Stopped'|'Error', number>
  for(const r of rows.value){ if(r.status==='Running') c.Running++; else if(r.status==='Stopped') c.Stopped++; else if(r.status==='Error') c.Error++ }
  return c
})

const filtered = computed(() => rows.value.filter(i => {
  if (q.value && !(i.name||'').includes(q.value)) return false
  if (status.value !== 'All' && i.status !== status.value) return false
  if (onlyStarred.value && !favorites.value.has(i.name)) return false
  return true
}))

const paged = computed(() => { const start = (currentPage.value - 1) * pageSize.value; return filtered.value.slice(start, start + pageSize.value) })

function savePref(){ try{ localStorage.setItem('pipeline_list_pref', JSON.stringify({ q: q.value, status: status.value, pageSize: pageSize.value, onlyStarred: onlyStarred.value })) } catch{} }
watch(q, () => { updateRouteQuery({ q: q.value }) })
onMounted(() => {
  try{
    const p = JSON.parse(localStorage.getItem('pipeline_list_pref')||'{}')
    if(p.q!=null) q.value=String(p.q)
    if(p.status) status.value=p.status
    if(p.pageSize) pageSize.value=p.pageSize
    if(typeof p.onlyStarred==='boolean') onlyStarred.value=p.onlyStarred
  }catch{}
  if (typeof route.query.q === 'string') q.value = route.query.q
  if (typeof route.query.status === 'string') status.value = (['Running','Stopped','Error'].includes(route.query.status) ? route.query.status : 'All') as any
  load()
})

watch(() => route.query.q, (val) => {
  if (typeof val === 'string') {
    q.value = val
    currentPage.value = 1
  }
})
watch(() => route.query.status, (val) => {
  if (typeof val === 'string' && ['All','Running','Stopped','Error'].includes(val)) {
    status.value = val as any
    currentPage.value = 1
  }
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <div class="left">
          <el-input v-model="q" placeholder="按名称过滤 (回车)" clearable class="w260" @keydown.enter.native="savePref">
            <template #prefix><el-icon><Search/></el-icon></template>
          </el-input>
        </div>
        <div class="chips">
          <el-check-tag :checked="status==='All'" @change="() => setStatus('All')">全部 <span class="cnt">{{ statusCounts.All }}</span></el-check-tag>
          <el-check-tag :checked="status==='Running'" type="success" @change="() => setStatus('Running')">运行中 <span class="cnt">{{ statusCounts.Running }}</span></el-check-tag>
          <el-check-tag :checked="status==='Stopped'" type="info" @change="() => setStatus('Stopped')">已停止 <span class="cnt">{{ statusCounts.Stopped }}</span></el-check-tag>
          <el-check-tag :checked="status==='Error'" type="danger" @change="() => setStatus('Error')">异常 <span class="cnt">{{ statusCounts.Error }}</span></el-check-tag>
          <el-divider direction="vertical"/>
          <el-check-tag :checked="onlyStarred" @change="(v:boolean)=>{ onlyStarred.value=v; currentPage=1; savePref() }">
            <el-icon style="vertical-align: -2px; margin-right:4px"><StarFilled/></el-icon>只看星标
          </el-check-tag>
        </div>
        <div class="right">
          <el-button size="small" @click="load" :loading="loading">刷新</el-button>
          <el-button size="small" @click="startSelected" :disabled="!selection.length">启动</el-button>
          <el-button size="small" @click="stopSelected" :disabled="!selection.length">停止</el-button>
          <el-button size="small" type="danger" @click="deleteSelected" :disabled="!selection.length">删除</el-button>
          <el-button type="primary" size="small" @click="create"><el-icon><Plus/></el-icon>新建</el-button>
        </div>
      </div>
    </template>

    <el-skeleton v-if="loading" :rows="6" animated/>
    <el-empty v-else-if="!loading && filtered.length===0" description="暂无数据"/>
    <el-table v-else :data="paged" height="520" stripe border size="small" @selection-change="onSelChange">
      <el-table-column type="selection" width="44" />
      <el-table-column label="星标" width="70">
        <template #default="{ row }">
          <el-button link @click="toggleFav(row.name)">
            <el-icon :style="{ color: isFav(row.name) ? '#ffb020' : 'var(--va-text-2)' }">
              <component :is="isFav(row.name) ? StarFilled : Star"/>
            </el-icon>
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" width="220" sortable />
      <el-table-column label="状态" width="120">
        <template #default="{ row }"><el-tag :type="statusType(row)" effect="dark">{{ row.status==='Running'?'运行中':row.status==='Stopped'?'已停止':row.status==='Error'?'异常':row.status }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="fps" label="FPS" width="100" sortable />
      <el-table-column prop="updatedAt" label="最近更新" width="180" sortable>
        <template #default="{ row }">{{ new Date(row.updatedAt).toLocaleString() }}</template>
      </el-table-column>
      <el-table-column prop="desc" label="描述" />
      <el-table-column label="运行" width="120">
        <template #default="{ row }"><el-switch :model-value="row.running" @change="() => toggleRun(row)" /></template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button link @click="router.push({ path: '/pipelines/detail/'+encodeURIComponent(row.name) })">详情</el-button>
          <el-button link type="primary" @click="edit(row)">编辑</el-button>
          <el-button link type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <el-pagination
        layout="total, sizes, prev, pager, next"
        :current-page="currentPage"
        :page-sizes="pageSizes"
        :page-size="pageSize"
        :total="filtered.length"
        @size-change="(v:number)=>{ pageSize.value=v; currentPage.value=1; savePref() }"
        @current-change="(v:number)=> currentPage.value=v"
        small
        background
      />
    </div>
  </el-card>

</template>

<style scoped>
.head{ display:flex; align-items:center; }
.left{ display:flex; align-items:center; gap:10px; }
.right{ margin-left:auto; display:flex; gap:10px; }
.w260{ width: 260px }
.w160{ width: 160px }
.pager{ margin-top: 8px; display:flex; justify-content:flex-end }
.chips{ display:flex; align-items:center; gap:8px; margin-left:12px }
.chips :deep(.el-check-tag){ border-radius: 18px; padding: 4px 10px; }
.cnt{ opacity:.8; margin-left:6px }
</style>
