# Video Source Manager — multi-stage build

FROM ubuntu:22.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    build-essential cmake ninja-build git pkg-config \
    libssl-dev libyaml-cpp-dev libjsoncpp-dev \
    libgrpc-dev libgrpc++-dev protobuf-compiler protobuf-compiler-grpc libprotobuf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN cmake -S video-source-manager -B build -G Ninja \
    -DCMAKE_PREFIX_PATH="/usr/lib/x86_64-linux-gnu/cmake/grpc;/usr/lib/cmake/grpc;/usr/lib/x86_64-linux-gnu/cmake/protobuf;/usr/lib/cmake/protobuf" \
 && cmake --build build -j

FROM ubuntu:22.04 AS runtime
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    ca-certificates libssl3 \
    libyaml-cpp0.7 libjsoncpp25 \
    libgrpc++1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /app/build/bin/VideoSourceManager /app/bin/VideoSourceManager
COPY video-source-manager/config /app/config

EXPOSE 7070 7071
ENTRYPOINT ["/app/bin/VideoSourceManager","/app/config"]
