<template>
  <div class="whep">
    <video ref="videoEl" class="video" playsinline :muted="muted" :autoplay="autoplay" />
    <div v-if="errorMsg" class="overlay error">{{ errorMsg }}</div>
    <div v-if="!connected && !errorMsg" class="overlay hint">{{ hintText }}</div>
    <div class="controls">
      <slot name="right"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

type PC = RTCPeerConnection

const props = withDefaults(defineProps<{ whepUrl?: string; autoplay?: boolean; token?: string; muted?: boolean }>(), {
  whepUrl: '',
  autoplay: true,
  token: '',
  muted: true
})

const videoEl = ref<HTMLVideoElement | null>(null)
const pcRef = ref<PC | null>(null)
const resourceUrl = ref<string>('')
const connected = ref(false)
const errorMsg = ref('')
const stopping = ref(false)

const hintText = computed(() => props.whepUrl ? '正在建立连接…' : '未选择数据源')

async function stopSession() {
  stopping.value = true
  try {
    if (resourceUrl.value) {
      try { await fetch(resourceUrl.value, { method: 'DELETE', mode: 'cors' }) } catch {}
      resourceUrl.value = ''
    }
    if (pcRef.value) {
      try { pcRef.value.getTransceivers().forEach(t => (t as any).stop && (t as any).stop()) } catch {}
      try { pcRef.value.getSenders().forEach(s => s.track && s.track.stop()) } catch {}
      try { pcRef.value.close() } catch {}
    }
  } finally {
    pcRef.value = null
    connected.value = false
    stopping.value = false
  }
}

async function startSession(url: string) {
  errorMsg.value = ''
  connected.value = false
  const pc = new RTCPeerConnection({ sdpSemantics: 'unified-plan', iceServers: [] } as any)
  pcRef.value = pc
  try {
    pc.addTransceiver('video', { direction: 'recvonly' })
    if (!props.muted) pc.addTransceiver('audio', { direction: 'recvonly' })

    pc.ontrack = (ev) => {
      if (videoEl.value && ev.streams && ev.streams[0]) {
        if (!videoEl.value.srcObject) videoEl.value.srcObject = ev.streams[0]
      }
    }
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'connected') connected.value = true
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed' || pc.connectionState === 'disconnected') connected.value = false
    }

    const offer = await pc.createOffer({ offerToReceiveVideo: true, offerToReceiveAudio: !props.muted } as any)
    await pc.setLocalDescription(offer)

    await new Promise<void>((resolve) => {
      let done = false
      const timer = setTimeout(() => { if (!done) { done = true; resolve() } }, 1500)
      pc.onicegatheringstatechange = () => {
        if (!done && pc.iceGatheringState === 'complete') { done = true; clearTimeout(timer); resolve() }
      }
    })

    const sdp = pc.localDescription?.sdp || offer.sdp || ''
    const headers: Record<string,string> = { 'Content-Type': 'application/sdp' }
    if (props.token) headers['Authorization'] = `Bearer ${props.token}`
    const resp = await fetch(url, { method: 'POST', mode: 'cors', headers, body: sdp })
    if (!resp.ok) throw new Error(`WHEP POST 失败: ${resp.status}`)
    const answer = await resp.text()
    const loc = resp.headers.get('Location') || ''
    resourceUrl.value = loc ? (new URL(loc, url)).toString() : ''
    await pc.setRemoteDescription({ type: 'answer', sdp: answer })
  } catch (e: any) {
    errorMsg.value = e?.message || 'WHEP 协商失败'
    await stopSession()
    throw e
  }
}

let retry = 0
async function ensureStart() {
  if (!props.autoplay || !props.whepUrl) return
  try {
    await startSession(props.whepUrl)
    retry = 0
  } catch {
    const delay = Math.min(16000, 1000 * Math.pow(2, retry++))
    if (retry <= 5) setTimeout(() => { if (props.whepUrl) ensureStart() }, delay)
  }
}

watch(() => props.whepUrl, async (val, old) => {
  if (val === old) return
  await stopSession()
  if (props.autoplay && val) ensureStart()
})

async function refresh() {
  await stopSession()
  if (props.autoplay && props.whepUrl) ensureStart()
}

defineExpose({ refresh })

onBeforeUnmount(() => { stopSession() })

if (props.autoplay && props.whepUrl) ensureStart()
</script>

<style scoped>
.whep{ position:relative; width:100%; padding-top:56.25%; background:#05070e; border-radius:10px; overflow:hidden; }
.video{ position:absolute; inset:0; width:100%; height:100%; object-fit:contain; background:#000; }
.overlay{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#9dbad9; font-size:14px; pointer-events:none; }
.overlay.hint{ color:#7aa0c7; }
.overlay.error{ color:#ff7777; }
.controls{ position:absolute; right:12px; bottom:12px; display:flex; gap:8px; z-index:2; }
</style>

