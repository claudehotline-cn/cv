<template>
  <div class="analysis-results">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>分析结果历史</span>
          <div class="header-controls">
            <el-select
              v-model="selectedSourceFilter"
              placeholder="筛选视频源"
              clearable
              style="width: 200px; margin-right: 10px"
            >
              <el-option label="全部视频源" value="" />
              <el-option
                v-for="source in videoStore.videoSources"
                :key="source.id"
                :label="source.name"
                :value="source.id"
              />
            </el-select>
            <el-button type="primary" @click="exportResults"
              >导出结果</el-button
            >
          </div>
        </div>
      </template>

      <el-table
        :data="filteredResults"
        size="small"
        max-height="600"
        @row-click="showResultDetail"
      >
        <el-table-column label="时间" width="180">
          <template #default="{ row }">
            {{ formatTimestamp(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column prop="source_id" label="视频源ID" width="120" />
        <el-table-column label="分析类型" width="120">
          <template #default="{ row }">
            <el-tag
              :type="row.type === 'object_detection' ? 'primary' : 'success'"
              size="small"
            >
              {{ row.type === "object_detection" ? "目标检测" : "实例分割" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="检测数量" width="100">
          <template #default="{ row }">
            <el-badge :value="row.detections.length" :max="99">
              <el-icon><DataAnalysis /></el-icon>
            </el-badge>
          </template>
        </el-table-column>
        <el-table-column label="检测对象" min-width="200">
          <template #default="{ row }">
            <el-tag
              v-for="detection in row.detections.slice(0, 3)"
              :key="detection.class_name"
              size="small"
              style="margin-right: 5px"
            >
              {{ detection.class_name }}
            </el-tag>
            <span
              v-if="row.detections.length > 3"
              style="color: #999; font-size: 12px"
            >
              +{{ row.detections.length - 3 }} 更多
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              link
              @click="showResultDetail(row)"
            >
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 20px; text-align: center">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="filteredResults.length"
          layout="total, sizes, prev, pager, next, jumper"
        />
      </div>
    </el-card>

    <!-- 结果详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="分析结果详情" width="800px">
      <div v-if="selectedResult">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="视频源ID">
            {{ selectedResult.source_id }}
          </el-descriptions-item>
          <el-descriptions-item label="分析时间">
            {{ formatTimestamp(selectedResult.timestamp) }}
          </el-descriptions-item>
          <el-descriptions-item label="分析类型">
            <el-tag
              :type="
                selectedResult.type === 'object_detection'
                  ? 'primary'
                  : 'success'
              "
            >
              {{
                selectedResult.type === "object_detection"
                  ? "目标检测"
                  : "实例分割"
              }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="检测数量">
            {{ selectedResult.detections.length }} 个对象
          </el-descriptions-item>
        </el-descriptions>

        <div style="margin-top: 20px">
          <h4>检测结果列表</h4>
          <el-table
            :data="selectedResult.detections"
            size="small"
            max-height="300"
          >
            <el-table-column prop="class_name" label="对象类别" width="120" />
            <el-table-column label="置信度" width="100">
              <template #default="{ row }">
                <el-progress
                  :percentage="Math.round(row.confidence * 100)"
                  :stroke-width="8"
                  text-inside
                />
              </template>
            </el-table-column>
            <el-table-column label="边界框" min-width="200">
              <template #default="{ row }">
                <span style="font-family: monospace; font-size: 12px">
                  ({{ row.bbox.x }}, {{ row.bbox.y }}, {{ row.bbox.width }},
                  {{ row.bbox.height }})
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 如果有处理后的图像，显示缩略图 -->
        <div v-if="selectedResult.processed_image_url" style="margin-top: 20px">
          <h4>处理后图像</h4>
          <img
            :src="selectedResult.processed_image_url"
            alt="处理后图像"
            style="max-width: 100%; max-height: 300px; border-radius: 8px"
          />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { useVideoStore } from "@/stores/videoStore";
import type { AnalysisResult } from "@/types";

const videoStore = useVideoStore();

// 数据
const selectedSourceFilter = ref("");
const currentPage = ref(1);
const pageSize = ref(20);
const detailDialogVisible = ref(false);
const selectedResult = ref<AnalysisResult | null>(null);

// 计算属性
const filteredResults = computed(() => {
  let results = videoStore.analysisResults;

  // 按视频源筛选
  if (selectedSourceFilter.value) {
    results = results.filter(
      (result) => result.source_id === selectedSourceFilter.value,
    );
  }

  // 分页
  const start = (currentPage.value - 1) * pageSize.value;
  const end = start + pageSize.value;
  return results.slice(start, end);
});

// 方法
const formatTimestamp = (timestamp: number) => {
  return new Date(timestamp).toLocaleString("zh-CN");
};

const showResultDetail = (result: AnalysisResult) => {
  selectedResult.value = result;
  detailDialogVisible.value = true;
};

type ExportRow = Record<string, string>;

const exportColumns: Array<{
  header: string;
  value: (result: AnalysisResult) => string;
}> = [
  {
    header: "\u65f6\u95f4",
    value: (result) => formatTimestamp(result.timestamp),
  },
  {
    header: "\u89c6\u9891\u6e90ID",
    value: (result) => result.source_id,
  },
  {
    header: "\u5206\u6790\u7c7b\u578b",
    value: (result) =>
      result.type === "object_detection"
        ? "\u76ee\u6807\u68c0\u6d4b"
        : "\u5b9e\u4f8b\u5206\u5272",
  },
  {
    header: "\u68c0\u6d4b\u6570\u91cf",
    value: (result) => result.detections.length.toString(),
  },
  {
    header: "\u68c0\u6d4b\u5bf9\u8c61",
    value: (result) =>
      result.detections.map((detection) => detection.class_name).join(", "),
  },
  {
    header: "\u5e73\u5747\u4fe1\u5fc3\u5ea6",
    value: (result) => {
      if (result.detections.length === 0) {
        return "0%";
      }
      const average =
        result.detections.reduce(
          (sum, detection) => sum + detection.confidence,
          0,
        ) / result.detections.length;
      return `${(average * 100).toFixed(2)}%`;
    },
  },
];

const exportResults = () => {
  if (filteredResults.value.length === 0) {
    return;
  }

  const dataToExport: ExportRow[] = filteredResults.value.map((result) => {
    const row: ExportRow = {};
    for (const column of exportColumns) {
      row[column.header] = column.value(result);
    }
    return row;
  });

  const headers = exportColumns.map((column) => column.header);
  const csvContent = [
    headers.join(","),
    ...dataToExport.map((row) =>
      headers.map((header) => `"${row[header] ?? ""}"`).join(","),
    ),
  ].join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.setAttribute("href", url);
  link.setAttribute(
    "download",
    `analysis_results_${new Date().toISOString().split("T")[0]}.csv`,
  );
  link.style.visibility = "hidden";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};
</script>

<style scoped>
.analysis-results {
  height: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-controls {
  display: flex;
  align-items: center;
}

:deep(.el-table__row) {
  cursor: pointer;
}

:deep(.el-table__row:hover) {
  background-color: #f5f5f5;
}
</style>
