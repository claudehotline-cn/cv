此目录为 Triton 模型仓库（不纳入 Git）。
示例结构：
  docker/model/
    yolov12x/
      config.pbtxt
      1/
        model.plan  或  model.onnx
请将实际模型文件放到此处，docker-compose 会将本目录挂载到 triton:/models。
