<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, computed } from 'vue'
import { ElMessage } from 'element-plus'

type Tile = { id: string; title: string }
type Place = { rowStart: number; colStart: number; rowSpan: number; colSpan: number }

const props = withDefaults(defineProps<{ items?: Tile[] }>(), { })

// 布局：2x2 / 3x3 / 4x4 / 1+5 / 1+7
const layoutKey = ref<'2x2'|'3x3'|'4x4'|'1+5'|'1+7'>('2x2')
const showOverlay = ref(true)
const perTileOverlayOff = ref<Set<string>>(new Set())
const hoverId = ref<string>('')
const active = ref<Tile|null>(null)
const autoRotate = ref(false)
let timer: any = null

const sources = ref<Tile[]>([])
function rebuild(count: number){
  const arr = (props.items && props.items.length) ? props.items.slice(0, count) : Array.from({ length: count }).map((_,i)=>({ id: `cam_${i+1}`, title: `Camera ${i+1}` }))
  sources.value = arr
}

const layoutConf = computed(() => {
  switch (layoutKey.value) {
    case '2x2': return { cols: 2, rows: 2, big: null as null }
    case '3x3': return { cols: 3, rows: 3, big: null as null }
    case '4x4': return { cols: 4, rows: 4, big: null as null }
    case '1+5': return { cols: 3, rows: 3, big: { rowSpan: 2, colSpan: 2 } }
    case '1+7': return { cols: 4, rows: 4, big: { rowSpan: 3, colSpan: 3 } }
  }
})

// 放大单格：记录被放大 tileId（仅 NxN 下有效，按 2x2 放大）
const bigTileId = ref<string | null>(null)

// 根据布局计算摆放位置
const placements = computed<Record<string, Place>>(() => {
  const { cols, rows, big } = layoutConf.value
  const map: Record<string, Place> = {}
  const used: boolean[][] = Array.from({ length: rows }, () => Array.from({ length: cols }, () => false))
  // 选择大图（Preset 固定，或 NxN 由 bigTileId 指定）
  let bigId: string | null = null
  let bigSpan: {rowSpan:number; colSpan:number} | null = null
  if (big) { bigId = sources.value[0]?.id || null; bigSpan = big }
  else if (bigTileId.value) { bigId = bigTileId.value; bigSpan = { rowSpan: Math.min(2, rows), colSpan: Math.min(2, cols) } }
  // 放置大图在左上角
  if (bigId && bigSpan) {
    const rs = Math.min(bigSpan.rowSpan, rows)
    const cs = Math.min(bigSpan.colSpan, cols)
    map[bigId] = { rowStart: 1, colStart: 1, rowSpan: rs, colSpan: cs }
    for (let r = 0; r < rs; r++) for (let c = 0; c < cs; c++) used[r][c] = true
  }
  // 顺序摆放其他
  const placeOne = (id: string) => {
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (!used[r][c]) { used[r][c] = true; map[id] = { rowStart: r+1, colStart: c+1, rowSpan: 1, colSpan: 1 }; return }
      }
    }
  }
  for (const s of sources.value) {
    if (s.id === bigId) continue
    placeOne(s.id)
  }
  return map
})

function openFull(s:Tile){ active.value = s }
function closeFull(){ active.value = null }
function toggleTileOverlay(id:string){ if (perTileOverlayOff.value.has(id)) perTileOverlayOff.value.delete(id); else perTileOverlayOff.value.add(id) }
function showOverlayFor(id:string){ return showOverlay.value && !perTileOverlayOff.value.has(id) }
function snapshot(id:string){ ElMessage.success(`已保存快照: ${id}`) }
function openNew(id:string){ window.open(`#/${id}`, '_blank') }
function toggleEnlarge(id:string){ bigTileId.value = (bigTileId.value === id ? null : id) }

// Drag & Drop 交换位置
function onDragStart(e:DragEvent, id:string){ e.dataTransfer?.setData('text/plain', id) }
function onDragOver(e:DragEvent){ e.preventDefault() }
function onDrop(e:DragEvent, targetId:string){ e.preventDefault(); const srcId = e.dataTransfer?.getData('text/plain'); if (!srcId || srcId===targetId) return; const a = sources.value.findIndex(s=>s.id===srcId); const b = sources.value.findIndex(s=>s.id===targetId); if (a<0||b<0) return; const arr = sources.value.slice(); const tmp = arr[a]; arr[a]=arr[b]; arr[b]=tmp; sources.value = arr }

// 自动轮播
function startRotate(){ stopRotate(); timer = setInterval(()=>{
  if (!sources.value.length) return
  const idx = active.value ? sources.value.findIndex(s => s.id===active.value!.id) : -1
  const next = sources.value[(idx + 1 + sources.value.length) % sources.value.length]
  active.value = next
}, 5000) }
function stopRotate(){ if (timer) clearInterval(timer); timer = null }

watch(autoRotate, (v)=>{ v ? startRotate() : stopRotate() })

// 根据布局重建数据
watch(layoutConf, ({cols,rows}) => { rebuild(cols*rows) }, { immediate: true })
watch(() => props.items, () => { const {cols,rows}=layoutConf.value; rebuild(cols*rows) }, { deep: true })

onMounted(()=>{ const onKey=(e:KeyboardEvent)=>{ if(e.key==='Escape') closeFull() }; window.addEventListener('keydown', onKey); (window as any).__vwk = onKey })
onBeforeUnmount(()=>{ stopRotate(); const onKey = (window as any).__vwk; if(onKey) window.removeEventListener('keydown', onKey) })
</script>

<template>
  <div class="vw">
    <div class="toolbar">
      <el-segmented v-model="layoutKey" :options="[
        {label:'2x2',value:'2x2'},
        {label:'3x3',value:'3x3'},
        {label:'4x4',value:'4x4'},
        {label:'1+5',value:'1+5'},
        {label:'1+7',value:'1+7'}
      ]" />
      <el-switch v-model="showOverlay" active-text="叠加"/>
      <el-switch v-model="autoRotate" active-text="自动轮播" style="margin-left:8px"/>
    </div>
    <div class="grid" :style="{ gridTemplateColumns: `repeat(${layoutConf.cols}, 1fr)` }">
      <div
        v-for="s in sources"
        :key="s.id"
        class="cell"
        draggable="true"
        @dragstart="onDragStart($event, s.id)"
        @dragover="onDragOver"
        @drop="onDrop($event, s.id)"
        @dblclick="openFull(s)" @mouseenter="hoverId=s.id" @mouseleave="hoverId=''"
        :style="{
          gridColumn: `${placements[s.id]?.colStart || 1} / span ${placements[s.id]?.colSpan || 1}`,
          gridRow: `${placements[s.id]?.rowStart || 1} / span ${placements[s.id]?.rowSpan || 1}`
        }"
      >
        <div class="video">{{ s.title }}</div>
        <div v-if="showOverlayFor(s.id)" class="overlay">{{ s.id }}</div>
        <div class="cell-actions" v-show="hoverId===s.id">
          <el-button size="small" text @click.stop="openFull(s)">全屏</el-button>
          <el-button size="small" text @click.stop="toggleTileOverlay(s.id)">{{ showOverlayFor(s.id) ? '隐藏叠加' : '显示叠加' }}</el-button>
          <el-button size="small" text @click.stop="snapshot(s.id)">快照</el-button>
          <el-button size="small" text @click.stop="openNew(s.id)">新窗</el-button>
          <el-button v-if="!layoutConf.big" size="small" text @click.stop="toggleEnlarge(s.id)">{{ bigTileId===s.id ? '还原' : '放大' }}</el-button>
        </div>
      </div>
    </div>
    <div v-if="active" class="fs">
      <div class="fs-body">
        <div class="fs-video">{{ active.title }}</div>
        <div class="fs-meta">{{ active.id }}</div>
        <el-button class="fs-close" size="small" @click="closeFull">退出全屏</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vw{ width:100%; }
.toolbar{ display:flex; align-items:center; gap:10px; margin-bottom:8px }
.grid{ display:grid; gap:8px }
.grid{ grid-auto-rows: 120px }
.cell{ position:relative; background: #000; border-radius:8px; overflow:hidden; min-height:120px }
.video{ color:#6b7280; display:flex; align-items:center; justify-content:center; height:100% }
.overlay{ position:absolute; right:8px; bottom:8px; color:#e5edf6; background: rgba(0,0,0,.35); padding:2px 6px; border-radius:4px; font-size:12px }
.cell-actions{ position:absolute; left:8px; top:8px; display:flex; gap:6px; background: rgba(0,0,0,.35); padding:2px 6px; border-radius:6px }
.fs{ position: fixed; inset:0; background: rgba(0,0,0,.8); display:flex; align-items:center; justify-content:center; backdrop-filter: blur(2px); }
.fs-body{ position: relative; width: 88vw; height: 72vh; background: #000; border-radius: 10px; overflow: hidden; box-shadow: 0 12px 36px rgba(0,0,0,.5) }
.fs-video{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#6b7280 }
.fs-meta{ position:absolute; right:12px; top:12px; color:#e5edf6; background: rgba(0,0,0,.35); padding:4px 8px; border-radius:6px; font-size:12px }
.fs-close{ position:absolute; left:12px; top:12px }
</style>
