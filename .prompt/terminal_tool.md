# 终端 API 使用指南

## ⚠️ 重要：端口占用注意事项

**🚨 本终端 API 服务使用以下端口，请勿占用：**
- **后端 API**: `2556` 端口
- **前端 Web UI**: `2555` 端口

**如果这些端口被占用：**
1. API 将无法正常启动
2. 请求会返回错误的响应（如 HTML 404 页面而不是 JSON）
3. **在使用前务必确保这两个端口未被其他应用占用**

检查端口占用：
```bash
lsof -i :2555 :2556
```

清理端口（如果需要）：
```bash
lsof -ti :2555 | xargs kill -9
lsof -ti :2556 | xargs kill -9
```

## 🎯 何时使用

**优先使用此终端 API 的场景：**
1. 运行阻塞命令（`npm start`, `npm run dev`, `python manage.py runserver` 等）
2. 需要持续运行的进程
3. 需要查看实时输出和调试信息
4. 命令执行时间超过 30 秒

**然后再使用自带工具的场景：**
- 快速命令（`ls`, `pwd`, `cat` 等）
- 不需要持续监控的操作

## 📡 API 端点

**Base URL:** `http://localhost:2556/api`

## 🚀 完整 API 列表

### 1. 创建终端
```bash
POST /terminals
{
  "userId": "assistant-1",      # 必填：你的用户ID
  "cwd": "/path/to/project",    # 必填：工作目录
  "shell": "/bin/bash",          # 可选：shell类型
  "cols": 80,                    # 可选：列数
  "rows": 24                     # 可选：行数
}
# 返回: { "data": { "terminalId": "xxx", "pid": 12345, ... } }
```

### 2. 查看终端列表
```bash
# 查看自己的所有终端
GET /terminals?userId=assistant-1

# 返回: { "data": { "terminals": [...], "count": 3 } }
```

### 3. 发送命令
```bash
POST /terminals/{terminalId}/input
{
  "userId": "assistant-1",
  "input": "npm start"           # 自动添加 \n
}
```

### 4. 读取输出
```bash
# 最后 N 行（推荐）
GET /terminals/{terminalId}/output?userId=assistant-1&mode=tail&tailLines=30

# 增量读取（避免重复）
GET /terminals/{terminalId}/output?userId=assistant-1&since={lastLine}

# 完整输出
GET /terminals/{terminalId}/output?userId=assistant-1&mode=full&maxLines=2000

# 首尾预览
GET /terminals/{terminalId}/output?userId=assistant-1&mode=head-tail&headLines=20&tailLines=20

# 🆕 清理 ANSI 序列（节省 token）
GET /terminals/{terminalId}/output?userId=assistant-1&mode=tail&tailLines=30&clean=true
```

### 5. 查看统计信息
```bash
GET /terminals/{terminalId}/stats?userId=assistant-1

# 返回: 输出行数、字节数、预估token等
```

### 6. 终止终端
```bash
DELETE /terminals/{terminalId}
{
  "userId": "assistant-1",
  "signal": "SIGTERM"            # 可选：默认 SIGTERM
}
```

### 7. 健康检查
```bash
GET /health

# 返回: { "status": "healthy", "activeTerminals": 5, ... }
```

## 💡 典型工作流

### 场景1：检查现有终端并复用

```bash
# 1. 先查看是否已有终端
GET /terminals?userId=assistant-1

# 2. 如果已存在，读取其输出
GET /terminals/{existingId}/output?userId=assistant-1&mode=tail&tailLines=30

# 3. 如果不存在或需要新建，再创建
POST /terminals { "userId": "assistant-1", "cwd": "/path" }
```

### 场景2：启动开发服务器并监控

```typescript
// 1. 查看现有终端避免重复
const list = await GET('/terminals?userId=assistant-1');

// 2. 创建新终端
const res = await POST('/terminals', {
  userId: "assistant-1",
  cwd: "/path/to/project"
});
const terminalId = res.data.terminalId;

// 3. 启动服务器
await POST(`/terminals/${terminalId}/input`, {
  userId: "assistant-1",
  input: "npm run dev"
});

// 4. 等待几秒
await sleep(3000);

// 5. 读取输出检查是否成功
const output = await GET(`/terminals/${terminalId}/output?userId=assistant-1&mode=tail&tailLines=30`);

// 6. 如果有错误，读取完整日志
if (output.includes("ERROR")) {
  const full = await GET(`/terminals/${terminalId}/output?userId=assistant-1&mode=full&maxLines=2000`);
  // 分析错误...
}
```

### 场景3：持续监控长时间运行的进程

```typescript
// 1. 创建终端并启动进程
const { terminalId } = await createTerminal();
await sendCommand(terminalId, "npm start");

// 2. 持续读取新输出
let lastLine = 0;
while (true) {
  const res = await GET(`/terminals/${terminalId}/output?userId=assistant-1&since=${lastLine}`);
  
  if (res.data.output) {
    console.log(res.data.output);  // 处理新输出
  }
  
  lastLine = res.data.nextReadFrom;
  await sleep(5000);  // 每5秒检查一次
}
```

### 场景4：执行多个命令序列

```typescript
// 1. 创建终端
const { terminalId } = await createTerminal({ cwd: "/project" });

// 2. 依次执行命令
await sendCommand(terminalId, "npm install");
await sleep(10000);  // 等待安装完成

await sendCommand(terminalId, "npm run build");
await sleep(5000);

// 3. 读取每一步的输出
const output = await readOutput(terminalId, { mode: "tail", tailLines: 50 });

// 4. 完成后清理
await DELETE(`/terminals/${terminalId}`, { userId: "assistant-1" });
```

## ⚠️ 重要提示

1. **先查看现有终端** - 使用 `GET /terminals?userId=xxx` 检查是否已有终端，避免重复创建
2. **userId 是必填的** - 所有操作都需要 userId，用于隔离不同用户的终端
3. **cwd 是必填的** - 创建终端时必须指定工作目录，避免路径混乱
4. **命令自动执行** - 无需手动添加 `\n`，API 会自动处理
5. **增量读取** - 使用 `since` 参数避免重复读取，节省 token
6. **统计信息** - 用 `/stats` 查看输出大小，评估是否需要分批读取
7. **优雅关闭** - 完成后用 DELETE 删除终端，释放资源
8. **🆕 清理 ANSI 序列** - AI 读取输出时使用 `clean=true` 参数去除颜色、动画等控制序列，大幅节省 token（spinner 动画可节省 90% 以上）

## 📊 输出模式

- `full` - 完整输出（默认，最多 1000 行）
- `tail` - 最后 N 行（适合查看最新状态）
- `head` - 前 N 行（适合查看启动日志）
- `head-tail` - 首尾各 N 行（大输出预览）

## 💡 Token 优化建议

**🆕 使用 `clean=true` 参数清理 ANSI 序列：**

```bash
# ❌ 不推荐：包含大量 ANSI 序列，消耗大量 token
GET /output?userId=assistant-1&mode=tail&tailLines=30

# ✅ 推荐：清理 ANSI 序列，节省 90% 以上 token
GET /output?userId=assistant-1&mode=tail&tailLines=30&clean=true
```

**何时使用 `clean=true`：**
- AI 分析输出内容时（去除无用的格式控制）
- 输出包含 spinner 动画或进度条时
- 需要提取纯文本信息时

**何时不使用 `clean=true`：**
- 前端 xterm.js 需要渲染彩色终端时
- 需要保留完整格式信息时

## 🔍 调试技巧

**遇到错误时：**
```bash
# 1. 先读取最后 50 行快速定位
GET /output?mode=tail&tailLines=50

# 2. 如果需要完整日志
GET /output?mode=full&maxLines=2000

# 3. 查看统计信息
GET /stats
```

**监控长时间运行的进程：**
```bash
# 记录上次读取位置
lastLine = 0

# 循环读取新输出
while (running) {
  output = GET /output?since={lastLine}
  lastLine = output.nextReadFrom
  sleep(5000)
}
```
