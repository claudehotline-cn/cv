FROM node:22-slim AS base

ENV NODE_ENV=production
# Agent Chat UI 默认连接 article-agent（可在构建时通过 --build-arg 覆盖）
ARG NEXT_PUBLIC_API_URL=/api
ARG NEXT_PUBLIC_ASSISTANT_ID=data_deep_agent
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_ASSISTANT_ID=${NEXT_PUBLIC_ASSISTANT_ID}

# 通过环境变量控制 Next.js 绑定地址和端口
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# 应用工作目录直接指向 agent-chat-ui 项目根
WORKDIR /app/agent-chat-ui

# 启用 pnpm（与上游项目保持一致）
RUN corepack enable && corepack prepare pnpm@10.5.1 --activate

# 先只拷贝 package.json 与 pnpm-lock.yaml，用于安装依赖
COPY third-party/agent-chat-ui/package.json third-party/agent-chat-ui/pnpm-lock.yaml ./

# 在项目目录下安装依赖，确保 next 等二进制在本目录 node_modules 中
RUN pnpm install --frozen-lockfile

# 再拷贝完整源码（避免因源码变更重复安装依赖）
COPY third-party/agent-chat-ui ./

# 注入 /articles 下载路由（避免直接修改 third-party 目录的 gitlink 指针）
COPY docker/agent-chat-ui/overrides/articles_route.ts /tmp/articles_route.ts
RUN mkdir -p "src/app/articles/[...slug]" && cp /tmp/articles_route.ts "src/app/articles/[...slug]/route.ts"

# 构建 Next.js 应用
RUN pnpm build

EXPOSE 3000

# 以生产模式启动 Next.js，绑定到 HOSTNAME:PORT（由环境变量控制）
CMD ["pnpm", "start"]
