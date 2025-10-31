<template>
  <div class="ge">
    <!-- 左侧悬浮竖向工具条（按类别分组） -->
    <div class="palette">
      <div class="pal-group">
        <div class="pal-title pre">预处理</div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('preprocess','preproc.letterbox', $event)" @dblclick.stop.prevent="addNodeQuick('preprocess','preproc.letterbox')">
          <div class="pal-name">Letterbox</div>
          <div class="pal-sub">preproc.letterbox</div>
        </div>
      </div>
      <div class="pal-group">
        <div class="pal-title model">模型</div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('model','model.ort', $event)" @dblclick.stop.prevent="addNodeQuick('model','model.ort')">
          <div class="pal-name">ONNX Runtime</div>
          <div class="pal-sub">model.ort</div>
        </div>
      </div>
      <div class="pal-group">
        <div class="pal-title post">后处理</div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('nms','post.yolo.nms', $event)" @dblclick.stop.prevent="addNodeQuick('nms','post.yolo.nms')">
          <div class="pal-name">YOLO NMS</div>
          <div class="pal-sub">post.yolo.nms</div>
        </div>
        <div class="pal-card" draggable="false" @mousedown="startDnd('overlay','overlay.cuda', $event)" @dblclick.stop.prevent="addNodeQuick('overlay','overlay.cuda')">
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
}>()

const containerRef = ref<HTMLDivElement | null>(null)
let graph: Graph | null = null
let dnd: Dnd | null = null

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

function makeNodeConfig(n: Partial<NodeJson> & { type: string; yamlType?: string }) {
  const title = n.name || n.yamlType || n.type
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
    data: { name: n.name || '', type: n.type, yamlType: n.yamlType, params: { ...(n.params || {}) } },
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
    panning: true,
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
          router: { name: 'manhattan' },
          zIndex: 1,
        })
      },
    },
  })
  graph.use(new Selection({ multiple: true, rubberband: true }))
  graph.use(new Transform({ rotating: false }))
  graph.use(new Snapline({ enabled: true }))

  graph.on('edge:connected', ({ edge }) => {
    try {
      const s = edge.getSourceCellId() as string
      const t = edge.getTargetCellId() as string
      emit('edge-connected', { source: s, target: t })
      emit('update:modelValue', snapshot())
    } catch {}
  })

  graph.on('edge:added', () => emit('update:modelValue', snapshot()))
  graph.on('edge:removed', () => emit('update:modelValue', snapshot()))
  graph.on('node:added', () => emit('update:modelValue', snapshot()))
  graph.on('node:removed', () => emit('update:modelValue', snapshot()))
  graph.on('node:moved', () => emit('update:modelValue', snapshot()))

  graph.on('cell:selected', ({ cell }) => {
    emit('update:selection', toNodeModel(cell))
  })
  graph.on('selection:changed', ({ selected }) => {
    const first = (selected?.[0]) || null
    emit('update:selection', first ? toNodeModel(first) : null)
  })

  dnd = new Dnd({
    target: graph,
    scaled: false,
    animation: true,
    draggingContainer: document.body,
    // 预览用克隆；落点也使用克隆，避免与预览/原始实例指针冲突
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
    graph!.addEdge({ source: { cell: e.source, port: 'out' }, target: { cell: e.target, port: 'in' } })
  })
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

function startDnd(kind: 'preprocess'|'model'|'nms'|'overlay', yamlType: string, evt: MouseEvent) {
  if (!graph || !dnd) return
  try { evt.preventDefault(); evt.stopPropagation(); } catch {}
  const node = graph.createNode(makeNodeConfig({ type: kind, yamlType }))
  dnd.start(node, evt)
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

onBeforeUnmount(() => { graph?.dispose(); graph = null; dnd = null })

watch(() => props.modelValue, (nv) => {
  // 外部变更时刷新画布
  if (!graph) return
  fromJSON(nv || { nodes: [], edges: [] })
})

defineExpose({ toJSON: snapshot, fromJSON, highlightInvalid, clearHighlight, addNodeFromPalette })
</script>

<style scoped>
.ge{ position: relative; height: 100%; min-height: calc(100vh - 64px); background: #0b121a; border-radius: 0; overflow: hidden; }
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
</style>
