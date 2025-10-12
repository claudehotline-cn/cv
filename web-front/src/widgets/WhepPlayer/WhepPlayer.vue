<template>
  <div class="whep">
    <el-form :inline="true" :model="form">
      <el-form-item label="WHEP URL">
        <el-input v-model="form.url" placeholder="http://127.0.0.1:8083/whep?stream=camera_01:det_720p" style="width:420px"/>
      </el-form-item>
      <el-form-item>
        <el-button @click="start" :loading="loading" type="primary">播放</el-button>
        <el-button @click="stop" :disabled="!pc">停止</el-button>
      </el-form-item>
    </el-form>
    <video ref="video" autoplay playsinline controls style="width:100%;max-height:420px;background:#000"></video>
    <div v-if="err" class="err">{{ err }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
const form = ref({ url: '' })
const video = ref<HTMLVideoElement | null>(null)
let pc: RTCPeerConnection | null = null
let abort: AbortController | null = null
const loading = ref(false)
const err = ref('')

async function start(){
  err.value = ''
  if(!form.value.url){ err.value = '请填写 WHEP URL'; return }
  loading.value = true
  try{
    pc = new RTCPeerConnection()
    pc.addTransceiver('video', { direction: 'recvonly' })
    pc.ontrack = (e) => { if (video.value && e.streams?.[0]) { video.value.srcObject = e.streams[0] } }
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    abort = new AbortController()
    const r = await fetch(form.value.url, { method:'POST', headers:{ 'Content-Type':'application/sdp' }, body: offer.sdp, signal: abort.signal })
    if(!r.ok){ throw new Error(await r.text()) }
    const sdp = await r.text()
    await pc.setRemoteDescription({ type:'answer', sdp })
  } catch(e:any){ err.value = String(e?.message||e) }
  finally { loading.value=false }
}

function stop(){ if(pc){ pc.close(); pc=null } if(abort){ abort.abort(); abort=null } if(video.value){ video.value.srcObject = null }
}
onUnmounted(stop)
</script>

<style scoped>
.err{ color:#f56c6c; margin-top: 8px; }
</style>

