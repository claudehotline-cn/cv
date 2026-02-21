# Agent Chat Vue Dockerfile (DEV 模式)
# 使用 Vite dev server 热重载

FROM node:22-slim

WORKDIR /app

# 复制依赖文件
COPY agent-chat-vue/package*.json ./

# 安装依赖
RUN npm install

# 复制源代码
COPY agent-chat-vue/ ./

# 暴露端口
EXPOSE 3000

# 启动开发服务器
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
