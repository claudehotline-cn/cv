<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { dataProvider } from '@/api/dataProvider'
import { ElMessage, ElNotification } from 'element-plus'
import { v4 as uuidv4 } from 'uuid'

const props = defineProps<{ modelValue: boolean; pipelines: {name:string}[] }>()
const emit  = defineEmits<{ (e:'update:modelValue', v:boolean):void; (e:'success'):void }>()
const visible = ref(props.modelValue)
watch(() => props.modelValue, v => visible.value = v)
watch(visible, v => emit('update:modelValue', v))

const form = reactive({
  attach_id: '',
  source_uri: '',
  pipeline_id: '',
  decoder: 'nvdec',
  fps: 25,
  reconnect_sec: 5
})
const rules = {
  source_uri: [
    { required: true, message: '请输入视频 URI', trigger: 'blur' },
    { pattern: /^(rtsp|rtmp|http|https):\/\//i, message: 'URI 格式不正确', trigger: 'blur' }
  ],
  pipeline_id: [{ required: true, message: '请选择 Pipeline', trigger: 'change' }],
  fps: [{ type: 'number', min: 1, max: 120, message: 'FPS 合法范围 1-120', trigger: 'change' }]
}

const formRef = ref()
const loading = ref(false)

function open() { form.attach_id = `att-${uuidv4().slice(0, 8)}` }
async function submit() {
  // @ts-ignore
  await formRef.value?.validate(async (ok:boolean) => {
    if (!ok) return
    loading.value = true
    try {
      await dataProvider.attachSource({
        attach_id: form.attach_id,
        source_uri: form.source_uri,
        pipeline_id: form.pipeline_id,
        options: { decoder: form.decoder, fps: String(form.fps), reconnect_sec: String(form.reconnect_sec) }
      })
      ElMessage.success('Attach 成功')
      visible.value = false
      emit('success')
      try {
        ElNotification({
          title: '已添加来源',
          message: `ID: ${form.attach_id}，可前往“Sources 预览”页面查看`,
          type: 'success',
          duration: 4000
        })
      } catch {}
      reset()
    } catch (e:any) {
      ElMessage.error(e?.message || 'Attach 失败，请检查 URI 与网络后重试')
    } finally { loading.value = false }
  })
}
function reset() {
  form.attach_id = ''
  form.source_uri = ''
  form.pipeline_id = ''
  form.decoder = 'nvdec'
  form.fps = 25
  form.reconnect_sec = 5
}
</script>

<template>
  <el-drawer v-model="visible" title="Attach 视频源" size="480px" @open="open">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
      <el-form-item label="Attach ID">
        <el-input v-model="form.attach_id" placeholder="自动生成，可自定义" />
      </el-form-item>

      <el-form-item label="视频 URI" prop="source_uri">
        <el-input v-model="form.source_uri" placeholder="rtsp://user:pwd@ip:554/..." />
      </el-form-item>

      <el-form-item label="目标 Pipeline" prop="pipeline_id">
        <el-select v-model="form.pipeline_id" filterable placeholder="选择 Pipeline">
          <el-option v-for="p in pipelines" :key="p.name" :label="p.name" :value="p.name" />
        </el-select>
      </el-form-item>

      <el-form-item label="解码器">
        <el-select v-model="form.decoder" style="width: 160px">
          <el-option label="NVIDIA NVDEC" value="nvdec" />
          <el-option label="FFmpeg SW" value="ffmpeg" />
        </el-select>
      </el-form-item>

      <el-form-item label="限制 FPS">
        <el-input-number v-model="form.fps" :min="1" :max="120" />
      </el-form-item>

      <el-form-item label="重连间隔(秒)">
        <el-input-number v-model="form.reconnect_sec" :min="1" :max="120" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="loading" @click="submit">Attach</el-button>
        <el-button @click="visible=false">取消</el-button>
      </el-form-item>
    </el-form>
  </el-drawer>
</template>

<style scoped>
:deep(.el-drawer__body){ padding-top: 8px; }
</style>

