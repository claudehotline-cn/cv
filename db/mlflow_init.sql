-- Initialize MLflow database (schemas are managed by MLflow on first run)
CREATE DATABASE IF NOT EXISTS `mlflow`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;
