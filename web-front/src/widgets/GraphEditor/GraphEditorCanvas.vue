<template>
  <div class="ge">
    <div class="toolbar">
      <el-button-group>
        <el-button size="small" @click="addNode('source')">源</el-button>
        <el-button size="small" @click="addNode('preprocess')">预处理</el-button>
        <el-button size="small" @click="addNode('model')">模型</el-button>
        <el-button size="small" @click="addNode('nms')">NMS</el-button>
        <el-button size="small" @click="addNode('overlay')">Overlay</el-button>
        <el-button size="small" @click="addNode('sink')">输出</el-button>
      </el-button-group>
      <el-button size="small" text @click="autoLayout">自动排布</el-button>
      <el-button size="small" text @click="loadSample">加载示例</el-button>
      <el-button size="small" text @click="emit('export', toJSON())">导出JSON</el-button>
      <el-upload :show-file-list="false" accept="application/json" :on-change="onImport">
        <el-button size="small" text>导入JSON</el-button>
      </el-upload>
      <div style="margin-left:auto"><el-button size="small" type="danger" text @click="removeSelected">删除</el-button></div>
    </div>
    <div ref="containerRef" class="canvas"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { Graph } from '@antv/x6'
import { Selection } from '@antv/x6-plugin-selection'
import { Transform } from '@antv/x6-plugin-transform'
import { Snapline } from '@antv/x6-plugin-snapline'
import { Dnd } from '@antv/x6-plugin-dnd'

import sample from './samples/demo.json'

const props = defineProps<{ modelValue?: any }>()
const emit = defineEmits<{
  (e:'update:selection', data:any):void;
  (e:'export', json:any):void;
  (e:'update:modelValue', v:any):void;
  (e:'edge-connected', payload:{ source:string, target:string }):void;
  (e:'connect-error', payload:{ msg:string }):void;
}>()

const containerRef = ref<HTMLDivElement|null>(null)
let graph: Graph
let dnd: Dnd
let lastWarnAt = 0

function getPortGroup(magnet: any): string {
  try {
    let el: any = magnet
    while (el && el.getAttribute) {
      const g = el.getAttribute('port-group')
      if (g) return g
      el = el.parentElement
    }
  } catch {}
  return ''
}

function warnOnce(msg: string) {
  const now = Date.now()
  if (now - lastWarnAt < 1000) return
  lastWarnAt = now
  try { (emit as any)('connect-error', { msg }) } catch {}
}

onMounted(()=>{
  graph = new Graph({
    container: containerRef.value!,
    background: { color: '#0b0e14' },
    grid: { visible: true, size: 10, type:'dot' },
    connecting: {
      router: 'manhattan',
      connector: { name:'rounded', args:{ radius:6 } },
      allowBlank: false, allowLoop: false, allowMulti: false, snap: true,
      highlight: true,
      // 高亮可连接端口/吸附端口
      highlighting: {
        magnetAvailable: { name: 'stroke', args: { padding: 4, attrs: { stroke: '#52c41a', strokeWidth: 2 } } },
        magnetAdsorbed:  { name: 'stroke', args: { padding: 4, attrs: { stroke: '#faad14', strokeWidth: 2 } } }
      },
      // 仅允许从“out”端口开始连线，避免拖拽节点与连线冲突
      validateMagnet({ magnet }) {
        const g = getPortGroup(magnet)
        if (g !== 'out') { warnOnce('只能从输出端口(out)发起连线'); return false }
        return true
      },
      createEdge() { return graph.createEdge({ shape:'edge', attrs:{ line:{ stroke:'#4b7fd1', strokeWidth:2, strokeOpacity:.95, targetMarker: { name: 'classic', size: 10 } } } }) },
      // 仅允许 out -> in
      validateConnection({ sourceCell, targetCell, sourceMagnet, targetMagnet }) {
        if (!sourceCell || !targetCell || !sourceMagnet || !targetMagnet) return false
        const sg = getPortGroup(sourceMagnet as any)
        const tg = getPortGroup(targetMagnet as any)
        if (sg !== 'out') { warnOnce('起点必须为输出端口(out)'); return false }
        if (tg !== 'in')  { warnOnce('终点必须为输入端口(in)'); return false }
        const st = (sourceCell.getData() as any)?.type
        const tt = (targetCell.getData() as any)?.type
        if (st==='sink') { warnOnce('Sink 节点不允许作为起点'); return false }
        if (tt==='source') { warnOnce('Source 节点不允许作为终点'); return false }
        return true
      }
    }
  })
  graph.use(new Selection({ enabled:true, multiple:true, rubberband:true, movable:true }))
  graph.use(new Transform({ resizing:true, rotating:false }))
  graph.use(new Snapline({ enabled:true }))

  graph.on('cell:selected', ({ cell }) => emit('update:selection', toNodeData(cell)))
  graph.on('cell:changed', () => emit('update:modelValue', toJSON()))
  graph.on('edge:connected', ({ edge }) => {
    try { emit('edge-connected', { source: edge.getSourceCellId(), target: edge.getTargetCellId() }) } catch {}
    emit('update:modelValue', toJSON())
  })
  graph.on('edge:mouseenter', ({ edge }) => { try { edge.attr('line', { stroke:'#7db3ff', strokeWidth:3 }) } catch {} })
  graph.on('edge:mouseleave', ({ edge }) => { try { edge.attr('line', { stroke:'#4b7fd1', strokeWidth:2 }) } catch {} })

  if (props.modelValue) fromJSON(props.modelValue)
})

onBeforeUnmount(()=> graph?.dispose())

function styleFor(kind: string){
  switch(kind){
    case 'source':   return { fill:'#113a8f', stroke:'#3a78ff' }
    case 'preprocess': return { fill:'#2a1152', stroke:'#a855f7' }
    case 'model':    return { fill:'#0f3b3a', stroke:'#10b981' }
    case 'nms':      return { fill:'#3f1f00', stroke:'#fa8c16' }
    case 'overlay':  return { fill:'#103f14', stroke:'#52c41a' }
    case 'sink':     return { fill:'#3d0d10', stroke:'#ff4d4f' }
    default:         return { fill:'#141822', stroke:'rgba(255,255,255,.1)' }
  }
}

function nodePorts(kind: string){
  const groups: any = {
    in: {
      position: 'left',
      markup: [
        { tagName:'circle', selector:'portBody' },
        { tagName:'text', selector:'portLabel' },
        { tagName:'title', selector:'portTip' }
      ],
      attrs: {
        portBody:  { r: 4, magnet: true, stroke: '#4b7fd1', fill: '#0b0e14' },
        portLabel: { text:'in', ref:'portBody', refX:-8, refY:0, fontSize:9, fill:'#9bb1d6', textAnchor:'end', dominantBaseline:'middle', opacity:.85, pointerEvents:'none' },
        portTip:   { text: 'in' }
      }
    },
    out: {
      position: 'right',
      markup: [
        { tagName:'circle', selector:'portBody' },
        { tagName:'text', selector:'portLabel' },
        { tagName:'title', selector:'portTip' }
      ],
      attrs: {
        portBody:  { r: 4, magnet: true, stroke: '#4b7fd1', fill: '#0b0e14' },
        portLabel: { text:'out', ref:'portBody', refX:8, refY:0, fontSize:9, fill:'#9bb1d6', textAnchor:'start', dominantBaseline:'middle', opacity:.85, pointerEvents:'none' },
        portTip:   { text: 'out' }
      }
    }
  }
  const items: any[] = []
  if (kind !== 'source') items.push({ group: 'in' })
  if (kind !== 'sink')   items.push({ group: 'out' })
  return { groups, items }
}

function addNode(kind: string) {
  const labelMap: Record<string,string> = { source:'⏺ Source', preprocess:'⚙️ Preprocess', model:'🤖 Model', nms:'🪄 NMS', overlay:'🖼 Overlay', sink:'⏬ Sink' }
  const x = 100 + Math.random()*300, y = 80 + Math.random()*240
  graph.addNode({
    x, y, width: 140, height: 44,
    attrs: { body: { stroke: styleFor(kind).stroke, fill: styleFor(kind).fill, rx: 8, ry: 8 }, label: { text: labelMap[kind] || kind, fill:'#e5edf6', fontSize: 13, fontWeight:600 } },
    ports: nodePorts(kind),
    data: { type: kind, name: `${kind}-${Date.now()%10000}`, params: {} }
  })
  emit('update:modelValue', toJSON())
}

function removeSelected(){ const cells = graph.getSelectedCells(); graph.removeCells(cells); emit('update:modelValue', toJSON()) }

function toNodeData(cell:any){ if (!cell || cell.isEdge()) return null; const { id } = cell; const data = cell.getData(); return { id, ...(data||{}) } }
function toJSON(){ const nodes = graph.getNodes().map(n => { const d = n.getData() || {}; return { id: n.id, name: d.name, type: d.type, params: d.params, position: n.getPosition() } }); const edges = graph.getEdges().map(e => ({ source: e.getSourceCellId(), target: e.getTargetCellId() })); return { nodes, edges } }
function fromJSON(json:any){
  graph.clearCells();
  const id2node: Record<string, any> = {};
  json.nodes?.forEach((n:any)=>{
    const kind = n.type || 'node'
    id2node[n.id] = graph.addNode({
      id: n.id,
      x: (n.position?.x ?? 100), y: (n.position?.y ?? 100), width: 140, height:44,
      attrs: { body:{ stroke: styleFor(kind).stroke, fill: styleFor(kind).fill, rx:8, ry:8 }, label:{ text: n.name || n.type, fill:'#e5edf6', fontSize:13, fontWeight:600 } },
      ports: nodePorts(kind),
      data: { type:n.type, name:n.name, params:n.params||{} }
    })
  });
  json.edges?.forEach((e:any)=>{ if (id2node[e.source] && id2node[e.target]){ graph.addEdge({ source: e.source, target: e.target, attrs:{ line:{ stroke:'#4b7fd1', strokeWidth:2 } } }) } })
}
function onImport(file:any){ try{ const fr = new FileReader(); fr.onload = () => { const json = JSON.parse(String(fr.result)); fromJSON(json); emit('update:modelValue', toJSON()) }; fr.readAsText(file.raw) }catch{} }
function autoLayout(){ const layers = ['source','preprocess','model','nms','overlay','sink']; const groups: Record<string, any[]> = {}; graph.getNodes().forEach(n=>{ const t = (n.getData() as any)?.type || 'other'; (groups[t]||(groups[t]=[])).push(n) }); const colW = 200; const baseX = 80; const baseY = 80; const rowH = 70; layers.forEach((t,idx)=>{ (groups[t]||[]).forEach((n,i)=> n.position({ x: baseX + idx*colW, y: baseY + i*rowH })) }); emit('update:modelValue', toJSON()) }

function loadSample(){ try{ fromJSON(sample as any); emit('update:modelValue', toJSON()) } catch {}
}

function highlightInvalid(ids: string[]){
  const set = new Set(ids)
  graph.getNodes().forEach(n => {
    const isBad = set.has(n.id)
    n.setAttrs({ body: { stroke: isBad ? '#ff5d6c' : 'rgba(255,255,255,.1)', strokeWidth: isBad ? 2 : 1 } })
  })
}

function clearHighlight(){ graph.getNodes().forEach(n => n.setAttrs({ body: { stroke: 'rgba(255,255,255,.1)', strokeWidth: 1 } })) }

defineExpose({ toJSON, fromJSON, autoLayout, highlightInvalid, clearHighlight })
</script>

<style scoped>
.ge{ display:flex; flex-direction:column; height:100%; }
.toolbar{ display:flex; align-items:center; gap:8px; padding:6px 6px 6px 0; }
.canvas{ flex:1; border:1px solid rgba(255,255,255,.08); border-radius:10px; overflow:hidden; min-height: 420px; }
</style>
