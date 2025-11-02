<template>
  <div class="ge">
    <!-- 左侧悬浮竖向工具条（按类别分组） -->
    <div class="palette">
      <div class="pal-group">
        <div class="pal-title pre">预处理</div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('preprocess','preproc.letterbox', $event)">
          <div class="pal-name">Letterbox</div>
          <div class="pal-sub">preproc.letterbox</div>
        </div>
      </div>
      <div class="pal-group">
        <div class="pal-title model">模型</div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('model','model.ort', $event)">
          <div class="pal-name">ONNX Runtime</div>
          <div class="pal-sub">model.ort</div>
        </div>
      </div>
      <div class="pal-group">
        <div class="pal-title post">后处理</div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('nms','post.yolo.nms', $event)">
          <div class="pal-name">YOLO NMS</div>
          <div class="pal-sub">post.yolo.nms</div>
        </div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('overlay','overlay.cuda', $event)">
          <div class="pal-name">Overlay(CUDA)</div>
          <div class="pal-sub">overlay.cuda</div>
        </div>
      </div>
    </div>

    <!-- 画布区域 -->
    <div class="canvas" ref="containerRef"></div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import { Graph } from '@antv/x6'
import { Dnd } from '@antv/x6-plugin-dnd'
import { Selection } from '@antv/x6-plugin-selection'
import { Transform } from '@antv/x6-plugin-transform'
import { Snapline } from '@antv/x6-plugin-snapline'

type NodeJson = { id:string; name?:string; type:string; yamlType?:string; params?:Record<string, any>; position?:{x:number;y:number} }
type EdgeJson = { source:string; target:string }
type GraphJson = { nodes: NodeJson[]; edges: EdgeJson[] }

const props = defineProps<{ modelValue: GraphJson }>()
const emit  = defineEmits<{
  (e: 'update:modelValue', v: GraphJson): void
  (e: 'update:selection', node: any | null): void
  (e: 'edge-connected', ev: { source: string, target: string }): void
  (e: 'connect-error', ev: { msg: string }): void
  (e: 'export', json: GraphJson): void
  (e: 'open-props', node: any): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null
let dnd: Dnd | null = null
let suppressWatch = false
let keydownHandler: ((e: KeyboardEvent)=>void) | null = null

// 统一的端口样式与分组：仅允许 out->in
const basePorts = {
  groups: {
    in: {
      position: 'left',
      label: { position: 'left', markup: [{ tagName: 'text', selector: 'label' }] },
      attrs: {
        circle: {
          r: 5, magnet: true, stroke: '#7aa2f7', strokeWidth: 1, fill: '#0d1b2a'
        },
        label: { text: 'in', fill: '#9aa6b2', fontSize: 10, refY: 0 }
      }
    },
    out: {
      position: 'right',
      label: { position: 'right', markup: [{ tagName: 'text', selector: 'label' }] },
      attrs: {
        circle: {
          r: 5, magnet: true, stroke: '#7aa2f7', strokeWidth: 1, fill: '#0d1b2a'
        },
        label: { text: 'out', fill: '#9aa6b2', fontSize: 10, refY: 0 }
      }
    }
  },
  items: [
    { group: 'in',   id: 'in' },
    { group: 'out',  id: 'out' },
  ],
}

const fillMap: Record<string,string> = {
  preprocess: '#243b55',
  model: '#1b3a4b',
  nms: '#283618',
  overlay: '#3a0ca3',
}
const strokeMap: Record<string,string> = {
  preprocess: '#3a86ff',
  model: '#00b4d8',
  nms: '#7cb518',
  overlay: '#b5179e',
}

function makeNodeConfig(n: Partial<NodeJson> & { type: string; yamlType?: string }) {
  const title = n.name || n.yamlType || n.type
  const fill = fillMap[n.type] || '#223'
  const stroke = strokeMap[n.type] || '#88a'
  return {
    shape: 'rect',
    width: 160,
    height: 44,
    label: title,
    attrs: {
      body: { fill, stroke, rx: 6, ry: 6, strokeWidth: 1 },
      label: { fill: '#e6edf3', fontSize: 12, fontWeight: 600 },
    },
    ports: basePorts,
    data: { name: n.name || '', type: n.type, yamlType: n.yamlType, params: { ...(n.params || {}) }, _stroke: stroke },
  }
}

function addNodeFromPalette(kind: 'preprocess'|'model'|'nms'|'overlay', yamlType: string, x=60, y=60) {
  const defaults: Record<string,Record<string,any>> = {
    preprocess: { out_w: '640', out_h: '640', use_cuda: '1' },
    model:      { in: 'tensor:det_input', outs: 'tensor:det_raw', model_path: '' },
    nms:        { conf: '0.65', iou: '0.45', use_cuda: '1' },
    overlay:    { alpha: '0.2', thickness: '3' },
  }
  const node = graph!.addNode({
    ...makeNodeConfig({ type: kind, yamlType }),
    x, y,
  })
  const mv = snapshot()
  emit('update:modelValue', mv)
  return node
}

function setupGraph(el: HTMLDivElement) {
  graph = new Graph({
    container: el,
    grid: true,
    background: { color: '#0b121a' },
    // 避免框选(rubberband)与画布拖拽冲突：仅允许右键（或触控板两指）拖拽画布
    // 左键拖拽用于选择/框选与节点操作
    panning: { enabled: true, eventTypes: ['rightMouseDown'] },
    mousewheel: { enabled: true, zoomAtMousePosition: true, modifiers: ['ctrl', 'meta'] },
    connecting: {
      allowBlank: false,
      allowLoop: false,
      allowNode: false,
      allowMulti: false,
      highlight: true,
      snap: true,
      validateConnection({ sourceMagnet, targetMagnet, sourcePort, targetPort }) {
        const ok = !!(sourceMagnet && targetMagnet && sourcePort === 'out' && targetPort === 'in')
        return ok
      },
      createEdge() {
        return graph!.createEdge({
          attrs: { line: { stroke: '#6ea8fe', strokeWidth: 1.6 } },
          data: { _stroke: '#6ea8fe', _strokeWidth: 1.6 },
          router: { name: 'manhattan' },
          zIndex: 1,
        })
      },
    },
  })
  graph.use(new Selection({ multiple: true, rubberband: true, showNodeSelectionBox: true, className: 'ge-selection' }))
  graph.use(new Transform({ rotating: false }))
  graph.use(new Snapline({ enabled: true }))

  // 快捷键：删除选中的节点/边；避免在输入框内触发
  const isTypingTarget = (el: any) => {
    if (!el) return false
    const tag = (el.tagName || '').toLowerCase()
    return tag === 'input' || tag === 'textarea' || el.isContentEditable
  }
  const removeSelection = () => {
    if (!graph) return
    const cells = graph.getSelectedCells?.() || []
    if (cells.length) graph.removeCells(cells)
  }
  // 附加全局键盘监听，确保无需 Keyboard 插件也可删除
  try {
    keydownHandler = (e: KeyboardEvent) => {
      const k = (e.key || '').toLowerCase()
      if ((k === 'delete' || k === 'backspace') && !isTypingTarget(e.target)) {
        e.preventDefault()
        removeSelection()
      }
    }
    window.addEventListener('keydown', keydownHandler)
  } catch {}

  graph.on('edge:connected', ({ edge }) => {
    try {
      const s = edge.getSourceCellId() as string
      const t = edge.getTargetCellId() as string
      emit('edge-connected', { source: s, target: t })
      emit('update:modelValue', snapshot())
    } catch {}
  })

  const sync = () => { suppressWatch = true; emit('update:modelValue', snapshot()); Promise.resolve().then(()=> suppressWatch=false) }
  graph.on('edge:added', sync)
  graph.on('edge:removed', sync)
  graph.on('node:added', sync)
  graph.on('node:removed', sync)
  graph.on('node:moved', sync)

  graph.on('cell:selected', ({ cell }) => {
    try {
      if (cell?.isNode?.()) {
        cell.attr('body/stroke', '#ffd166')
        cell.attr('body/strokeWidth', 2)
      } else if (cell?.isEdge?.()) {
        cell.attr('line/stroke', '#ffd166')
        cell.attr('line/strokeWidth', 2.4)
      }
    } catch {}
    emit('update:selection', toNodeModel(cell))
  })
  graph.on('cell:unselected', ({ cell }) => {
    try {
      if (cell?.isNode?.()) {
        const d = cell.getData?.() || {}
        const fallback = strokeMap?.[d?.type] || d?._stroke || '#88a'
        cell.attr('body/stroke', fallback)
        cell.attr('body/strokeWidth', 1)
      } else if (cell?.isEdge?.()) {
        const d = cell.getData?.() || {}
        const s = d?._stroke || '#6ea8fe'
        const w = d?._strokeWidth || 1.6
        cell.attr('line/stroke', s)
        cell.attr('line/strokeWidth', w)
      }
    } catch {}
  })
  graph.on('selection:changed', ({ selected }) => {
    const first = (selected?.[0]) || null
    emit('update:selection', first ? toNodeModel(first) : null)
  })

  // 双击节点：打开属性面板（由父组件处理）
  graph.on('node:dblclick', ({ node }) => {
    try { const model = toNodeModel(node); emit('update:selection', model); if (model) emit('open-props', model) } catch {}
  })

  // 视口变化：缩放/平移时通知父组件（用于工具条吸附）
  try {
    graph.on('scale', () => { emit('update:modelValue', snapshot()) })
    graph.on('translate', () => { /* no-op; parent may listen via custom event if needed */ })
  } catch {}

  dnd = new Dnd({
    target: graph,
    scaled: false,
    animation: true,
    draggingContainer: document.body,
    // 预览与落点均使用克隆，可靠落入画布
    getDragNode(node){ return node.clone() },
    getDropNode(node){ return node.clone() },
  })
}

function toNodeModel(cell: any): any | null {
  if (!cell || cell.isEdge?.()) return null
  const data = cell.getData?.() || {}
  return { id: cell.id, name: data.name || cell.id, type: data.type, yamlType: data.yamlType, params: { ...(data.params || {}) } }
}

function snapshot(): GraphJson {
  if (!graph) return { nodes: [], edges: [] }
  const nodes: NodeJson[] = []
  const edges: EdgeJson[] = []
  graph.getNodes().forEach(n => {
    const pos = n.getPosition()
    const data = n.getData() || {}
    nodes.push({ id: n.id, name: data.name || '', type: data.type, yamlType: data.yamlType, params: { ...(data.params || {}) }, position: pos })
  })
  graph.getEdges().forEach(e => {
    const s = e.getSourceCellId() as string
    const t = e.getTargetCellId() as string
    if (s && t) edges.push({ source: s, target: t })
  })
  return { nodes, edges }
}

function clear() {
  graph?.clearCells()
}

function fromJSON(json: GraphJson) {
  clear()
  const idToCell: Record<string, any> = {}
  ;(json.nodes || []).forEach(n => {
    const cfg = makeNodeConfig({ type: n.type, yamlType: n.yamlType, name: n.name, params: n.params })
    const cell = graph!.addNode({ ...cfg, x: n.position?.x ?? 60, y: n.position?.y ?? 60, id: n.id })
    idToCell[n.id] = cell
  })
  ;(json.edges || []).forEach(e => {
    if (!idToCell[e.source] || !idToCell[e.target]) return
    graph!.addEdge({
      source: { cell: e.source, port: 'out' },
      target: { cell: e.target, port: 'in' },
      attrs: { line: { stroke: '#6ea8fe', strokeWidth: 1.6 } },
      data: { _stroke: '#6ea8fe', _strokeWidth: 1.6 }
    })
  })
  try { autoArrange() } catch {}
  nextTick(() => emit('update:modelValue', snapshot()))
}

function highlightInvalid(ids: string[]) {
  if (!graph) return
  const set = new Set(ids)
  graph.getNodes().forEach(n => {
    const bad = set.has(n.id)
    n.attr('body/stroke', bad ? '#ff6b6b' : '#88a')
  })
}

function clearHighlight() {
  if (!graph) return
  graph.getNodes().forEach(n => n.attr('body/stroke', '#88a'))
}

function fitView() {
  if (!graph) return
  try {
    const nodes = graph.getNodes()
    if (!nodes.length) return
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    nodes.forEach(n => {
      const p = n.getPosition()
      const sz = (n.getSize && n.getSize()) || { width: 160, height: 44 }
      const x1 = p.x, y1 = p.y, x2 = p.x + (sz.width||160), y2 = p.y + (sz.height||44)
      if (x1 < minX) minX = x1
      if (y1 < minY) minY = y1
      if (x2 > maxX) maxX = x2
      if (y2 > maxY) maxY = y2
    })
    if (!isFinite(minX) || !isFinite(minY) || !isFinite(maxX) || !isFinite(maxY)) return
    const el = containerRef.value as HTMLDivElement
    const cw = Math.max(200, el?.clientWidth || 800)
    const ch = Math.max(200, el?.clientHeight || 600)
    const bboxW = Math.max(1, maxX - minX)
    const bboxH = Math.max(1, maxY - minY)
    const dx = Math.floor((cw - bboxW) / 2 - minX)
    const dy = Math.floor((ch - bboxH) / 2 - minY)
    if (dx !== 0 || dy !== 0) nodes.forEach(n => { try { n.translate(dx, dy) } catch {} })
  } catch {}
}
function startDnd(kind: 'preprocess'|'model'|'nms'|'overlay', yamlType: string, evt: MouseEvent) {
  if (!graph || !dnd) return
  try { evt.preventDefault(); evt.stopPropagation(); } catch {}
  try {
    document.body.classList.add('ge-dragging')
    const onUp = () => { document.body.classList.remove('ge-dragging'); window.removeEventListener('mouseup', onUp) }
    window.addEventListener('mouseup', onUp, { once: true })
  } catch {}
  const node = graph.createNode(makeNodeConfig({ type: kind, yamlType }))
  dnd.start(node, evt)
}

function autoArrange() {
  if (!graph) return
  try {
    const nodes = graph.getNodes()
    const edges = graph.getEdges()
    if (!nodes.length) return
    const ids = new Set(nodes.map(n=>n.id))
    const indeg = new Map<string, number>()
    const next = new Map<string, string[]>()
    ids.forEach(id => { indeg.set(id, 0); next.set(id, []) })
    edges.forEach(e => {
      const s = e.getSourceCellId?.() as string
      const t = e.getTargetCellId?.() as string
      if (ids.has(s) && ids.has(t)) {
        indeg.set(t, (indeg.get(t)||0)+1)
        next.get(s)!.push(t)
      }
    })
    const q: string[] = []
    indeg.forEach((d, id) => { if (d===0) q.push(id) })
    if (!q.length) q.push(...Array.from(ids))
    const layer = new Map<string, number>()
    q.forEach(id => layer.set(id, 0))
    const order: string[] = []
    while (q.length) {
      const u = q.shift()!
      order.push(u)
      for (const v of (next.get(u)||[])) {
        const lv = Math.max(layer.get(v)||0, (layer.get(u)||0)+1); layer.set(v, lv)
        indeg.set(v, (indeg.get(v)||0)-1)
        if ((indeg.get(v)||0)===0) q.push(v)
      }
    }
    const groups = new Map<number, string[]>()
    for (const id of order) {
      const l = layer.get(id)||0
      if (!groups.has(l)) groups.set(l, [])
      groups.get(l)!.push(id)
    }
    const dx = 220, dy = 96
    const startX = 60, startY = 60
    Array.from(groups.entries()).forEach(([l, arr]) => {
      arr.forEach((id, idx) => {
        const n = nodes.find(x=>x.id===id); if (!n) return
        const x = startX + l*dx
        const y = startY + idx*dy
        try { n.position(x, y) } catch {}
      })
    })
  } catch {}
}
function addNodeQuick(kind: 'preprocess'|'model'|'nms'|'overlay', yamlType: string){
  if (!graph) return
  const el = containerRef.value as HTMLDivElement
  const cx = Math.max(40, (el?.clientWidth||800)/2)
  const cy = Math.max(40, (el?.clientHeight||600)/2)
  const cell = graph.addNode({ ...makeNodeConfig({ type: kind, yamlType }), x: cx, y: cy })
  emit('update:modelValue', snapshot())
  return cell
}

onMounted(() => {
  if (!containerRef.value) return
  setupGraph(containerRef.value)
  if (props.modelValue && (props.modelValue.nodes?.length || props.modelValue.edges?.length)) fromJSON(props.modelValue)
})

onBeforeUnmount(() => {
  try { if (keydownHandler) window.removeEventListener('keydown', keydownHandler) } catch {}
  keydownHandler = null
  graph?.dispose(); graph = null; dnd = null
})

watch(() => props.modelValue, (nv) => {
  // 外部变更时刷新画布；忽略自身触发的同步，避免拖拽落点过程的重复添加
  if (!graph || suppressWatch) return
  return // disabled auto fromJSON
})

defineExpose({ toJSON: snapshot, fromJSON, highlightInvalid, clearHighlight, addNodeFromPalette, fitView, autoArrange })
</script>

<style scoped>
/* 选中样式与框选样式增强（X6 Selection 插件） */
:deep(.x6-widget-selection-box) {
  border: 1.5px solid #ffd166 !important;
}
:deep(.x6-widget-selection-inner) {
  border: 1px dashed #ffd166 !important;
}
:deep(.x6-widget-selection-rubberband) {
  border: 1.5px solid #4dabf7aa !important;
  background: #4dabf733 !important;
}

/* 边选中态高亮（不依赖放缩） */
:deep(svg .x6-edge path) {
  vector-effect: non-scaling-stroke;
}
:deep(svg g.x6-edge-selected path) {
  stroke: #ffd166 !important;
  stroke-width: 2.4px !important;
}
</style>

<style scoped>
.ge{ position: relative; height: 100%; min-height: 100%; background: #0b121a; border-radius: 0; overflow: hidden; }
.canvas{ position:absolute; inset:0 0 0 0; }
.palette{ position:absolute; left:8px; top:8px; width: 220px; display:flex; flex-direction:column; gap:12px; z-index:2; }
.pal-group{ background: rgba(22,27,34,.85); border:1px solid rgba(99,110,123,.25); border-radius:8px; padding:10px; backdrop-filter: blur(4px); }
.pal-title{ font-weight:600; font-size:12px; letter-spacing:.5px; margin-bottom:8px; color:#e6edf3; }
.pal-title.pre{ color:#58a6ff; }
.pal-title.model{ color:#8bd3dd; }
.pal-title.post{ color:#8bc34a; }
.pal-card{ padding:8px 10px; border:1px solid rgba(148,163,184,.25); border-radius:6px; cursor:grab; background:linear-gradient(180deg, rgba(20,26,33,.9), rgba(12,18,24,.9)); }
.pal-card + .pal-card{ margin-top:8px; }
.pal-card:hover{ border-color:#6ea8fe; box-shadow:0 0 0 1px rgba(110,168,254,.25) inset; }
.pal-name{ color:#e6edf3; font-size:12px; font-weight:600; }
.pal-sub{ color:#94a3b8; font-size:11px; }

/* X6 端口 hover 动效 */
:deep(.x6-port) circle{ transition: transform .12s ease; }
:deep(.x6-port:hover) circle{ transform: scale(1.35); }

/* 正在拖拽时，禁用工具条命中，确保事件传递给画布容器 */
:global(body.ge-dragging) .palette{ pointer-events: none !important; }
</style>


