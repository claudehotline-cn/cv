# Controlplane — multi-stage build

FROM ubuntu:22.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    build-essential cmake ninja-build git pkg-config \
    libssl-dev libyaml-cpp-dev libjsoncpp-dev \
    nlohmann-json3-dev \
    libgrpc-dev libgrpc++-dev protobuf-compiler protobuf-compiler-grpc libprotobuf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN cmake -S controlplane -B build -G Ninja \
    -DCMAKE_PREFIX_PATH="/usr/lib/x86_64-linux-gnu/cmake/grpc;/usr/lib/cmake/grpc;/usr/lib/x86_64-linux-gnu/cmake/protobuf;/usr/lib/cmake/protobuf" \
 && cmake --build build -j

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    libssl3 ca-certificates libyaml-cpp0.7 libjsoncpp25 \
    libgrpc++1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /app/build/bin/controlplane /app/bin/controlplane
COPY controlplane/config /app/config

EXPOSE 18080
ENTRYPOINT ["/app/bin/controlplane","/app/config"]

