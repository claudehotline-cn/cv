# RAG UI Dockerfile
FROM node:20-slim AS builder

WORKDIR /app

# 安装依赖
COPY rag-ui/package.json rag-ui/package-lock.json ./
RUN npm ci

# 复制源码并构建
COPY rag-ui ./
RUN npm run build

# 生产环境 - 使用Nginx
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制Nginx配置
COPY docker/rag-ui/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
