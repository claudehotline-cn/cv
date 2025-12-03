# Web Frontend (Vite build + Nginx serve)

FROM node:20-alpine AS build
WORKDIR /app
COPY web-front/package*.json ./
# 优先使用锁文件；若不存在则回退到 npm install
RUN if [ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]; then npm ci; else npm install; fi
COPY web-front ./
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
