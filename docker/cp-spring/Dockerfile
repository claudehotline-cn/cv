FROM maven:3.9.9-eclipse-temurin-21 AS build

WORKDIR /app

# 可选：从宿主机预先下载好的 Maven 本地仓库复制到构建容器中，避免大量重复下载
# 需要先在宿主机项目根目录执行一次：
#   mkdir -p .repository
#   docker run --rm -v /home/chaisen/projects/cv/.repository:/root/.m2/repository \
#      -v /home/chaisen/projects/cv/controlplane-spring:/app -w /app \
#      maven:3.9.9-eclipse-temurin-21 mvn -DskipTests dependency:go-offline
COPY .repository /root/.m2/repository

# 第一步：只复制 pom，用于补全缺少的依赖（这一层可缓存）
COPY controlplane-spring/pom.xml /app/pom.xml
RUN mvn -DskipTests dependency:go-offline

# 第二步：复制源码并真正执行打包；只有源码或 pom 变化时才会重跑
COPY controlplane-spring/src /app/src
RUN mvn -DskipTests package

FROM eclipse-temurin:21-jre

WORKDIR /app

COPY --from=build /app/target/controlplane-spring-0.1.0-SNAPSHOT.jar /app/app.jar
# 复用现有 CP 的 mTLS 证书路径（供 gRPC 客户端使用）
COPY controlplane/config/certs /app/config/certs

EXPOSE 18080

ENTRYPOINT ["java","-jar","/app/app.jar"]
