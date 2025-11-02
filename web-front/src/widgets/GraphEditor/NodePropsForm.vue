<template>
  <el-card shadow="never" class="form-card">
    <template #header>
      <div class="head"><b>节点属性</b><span v-if="model">（{{ model.type }}）</span></div>
    </template>

    <el-empty v-if="!model" description="请选择一个节点" />
    <template v-else>
      <el-alert
        v-if="fieldErrors.length"
        type="error"
        show-icon
        :closable="false"
        class="alert"
      >
        <ul class="err-list">
          <li v-for="(msg, idx) in fieldErrors" :key="idx">{{ msg }}</li>
        </ul>
      </el-alert>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="120px"
        size="small"
      >
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" placeholder="用于识别的节点名称" /></el-form-item>

        <template v-if="model.type==='source'">
          <el-form-item label="视频 URI" prop="uri"><el-input v-model="form.params.uri" placeholder="rtsp://user:pwd@ip:554/..." /></el-form-item>
          <el-form-item label="解码器">
            <el-select v-model="form.params.decoder" placeholder="选择硬件/软件解码">
              <el-option label="NVIDIA NVDEC" value="nvdec" />
              <el-option label="FFmpeg 软件" value="ffmpeg" />
            </el-select>
          </el-form-item>
        </template>

        <template v-else-if="model.type==='model'">
          <el-form-item label="模型文件 URI" prop="modelUri"><el-input v-model="form.params.modelUri" placeholder="models/detector.onnx" /></el-form-item>
          <el-form-item label="推理 Provider">
            <el-select v-model="form.params.provider" placeholder="选择推理后端">
              <el-option label="TensorRT" value="tensorrt" />
              <el-option label="CUDA Execution Provider" value="cuda" />
              <el-option label="CPU" value="cpu" />
            </el-select>
          </el-form-item>
          <el-form-item label="启用 IO 绑定">
            <el-switch v-model="form.params.iobinding" />
          </el-form-item>
        </template>

        <template v-else-if="model.type==='nms'">
          <el-form-item label="IoU 阈值" prop="iou"><el-input-number v-model="form.params.iou" :min="0" :max="1" :step="0.05" /></el-form-item>
          <el-form-item label="置信阈值" prop="conf"><el-input-number v-model="form.params.conf" :min="0" :max="1" :step="0.05" /></el-form-item>
          <el-form-item label="最大检测数"><el-input-number v-model="form.params.maxDet" :min="1" :max="1000" /></el-form-item>
        </template>

        <template v-else-if="model.type==='overlay'">
          <el-form-item label="调色板"><el-select v-model="form.params.palette"><el-option label="品牌深色" value="brand-dark" /><el-option label="经典" value="classic" /></el-select></el-form-item>
          <el-form-item label="描边宽度"><el-input-number v-model="form.params.thickness" :min="1" :max="6" /></el-form-item>
        </template>

        <template v-else-if="model.type==='sink'">
          <el-form-item label="WHEP URL" prop="whepUrl"><el-input v-model="form.params.whepUrl" placeholder="https://edge/whep/..." /></el-form-item>
          <el-form-item label="输出 FPS"><el-input-number v-model="form.params.fps" :min="1" :max="120" /></el-form-item>
        </template>

        <el-divider />
        <el-space>
          <el-button type="primary" @click="save">保存</el-button>
          <el-button @click="reset">重置</el-button>
        </el-space>
      </el-form>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{ model: any | null; errors?: string[] }>()
const emit  = defineEmits<{ (e:'update', data:any):void }>()
const formRef = ref()

const form = reactive<any>({ id:'', name:'', type:'', params:{} })

watch(() => props.model, (m) => {
  if (!m) return
  form.id = m.id
  form.name = m.name || ''
  form.type = m.type
  form.params = { ...(m.params || {}) }
}, { immediate: true })

const fieldErrors = computed(() => props.errors ?? [])

const rules = {
  name: [{ required:true, message:'请输入节点名称', trigger:'blur' }],
  modelUri: [{ required:true, message:'请填写模型文件路径', trigger:'blur' }],
  uri: [
    { required: true, message: '请输入 RTSP/HTTP URI', trigger: 'blur' },
    { pattern:/^(rtsp|rtmp|http|https):\/\//i, message:'URI 格式不正确，应以 rtsp/rtmp/http(s) 开头', trigger:'blur' }
  ],
  whepUrl: [
    { required:true, message:'请输入 WHEP URL', trigger:'blur' },
    { pattern:/^https?:\/\//i, message:'URL 需以 http(s) 开头', trigger:'blur' }
  ],
  iou: [{ type:'number', min:0, max:1, message:'范围 0~1', trigger:'change' }],
  conf:[{ type:'number', min:0, max:1, message:'范围 0~1', trigger:'change' }],
}

function save(){
  // @ts-ignore
  formRef.value?.validate((ok:boolean) => {
    if (!ok) return
    emit('update', JSON.parse(JSON.stringify(form)))
    ElMessage.success('已保存到草稿（需点击 Apply 才会下发）')
  })
}

function reset(){
  if (!props.model) return
  form.id = props.model.id
  form.name = props.model.name || ''
  form.type = props.model.type
  form.params = { ...(props.model.params || {}) }
}
</script>

<style scoped>
.form-card{ height:100%; }
.head{ display:flex; gap:8px; align-items:center; }
.alert{ margin-bottom:12px; }
.err-list{ margin:0; padding-left:18px; font-size:12px; line-height:1.6; }
</style>
