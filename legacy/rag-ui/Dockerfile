# Build stage
FROM node:22-slim as build-stage
WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com/
RUN npm install
COPY . .
RUN npm run build

# Production stage
FROM nginx:stable-alpine as production-stage
COPY --from=build-stage /app/dist /usr/share/nginx/html
# Copy custom nginx config if needed, otherwise default is used
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
