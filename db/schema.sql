-- MySQL 8.0+ schema for CV Control Plane storage
-- Safe to run multiple times (uses IF NOT EXISTS)

-- Database
CREATE DATABASE IF NOT EXISTS `cv_cp`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;
USE `cv_cp`;

-- Optional but recommended
SET NAMES utf8mb4;
SET sql_mode = 'STRICT_ALL_TABLES';

-- 1) Sources: camera/stream registry and latest observed caps
CREATE TABLE IF NOT EXISTS `sources` (
  `id`         VARCHAR(64)   NOT NULL,
  `uri`        VARCHAR(1024) NOT NULL,
  `status`     VARCHAR(32)   NOT NULL DEFAULT 'Unknown',
  `caps`       JSON          NULL,
  `fps`        DOUBLE        NULL,
  `created_at` DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_sources_status` (`status`),
  INDEX `idx_sources_updated` (`updated_at`),
  CHECK (JSON_VALID(`caps`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) Pipelines: named pipeline profiles
CREATE TABLE IF NOT EXISTS `pipelines` (
  `name`            VARCHAR(64)  NOT NULL,
  `graph_id`        VARCHAR(64)  NULL,
  `default_model_id` VARCHAR(128) NULL,
  `encoder_cfg`     JSON         NULL,
  `created_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`name`),
  CHECK (JSON_VALID(`encoder_cfg`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3) Graphs: graph registry and requirements
CREATE TABLE IF NOT EXISTS `graphs` (
  `id`         VARCHAR(64)  NOT NULL,
  `name`       VARCHAR(128) NOT NULL,
  `requires`   JSON         NULL,
  `file_path`  VARCHAR(512) NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CHECK (JSON_VALID(`requires`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4) Models: model registry and defaults
CREATE TABLE IF NOT EXISTS `models` (
  `id`         VARCHAR(128) NOT NULL,
  `task`       VARCHAR(32)  NULL,
  `family`     VARCHAR(64)  NULL,
  `variant`    VARCHAR(64)  NULL,
  `path`       VARCHAR(512) NULL,
  `conf`       DOUBLE       NULL,
  `iou`        DOUBLE       NULL,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5) Sessions: subscribe lifecycle for analysis
CREATE TABLE IF NOT EXISTS `sessions` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `stream_id`  VARCHAR(64)  NOT NULL,
  `pipeline`   VARCHAR(64)  NOT NULL,
  `model_id`   VARCHAR(128) NULL,
  `status`     VARCHAR(32)  NOT NULL,
  `error_msg`  VARCHAR(256) NULL,
  `started_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `stopped_at` DATETIME     NULL,
  PRIMARY KEY (`id`),
  INDEX `idx_sessions_stream_time` (`stream_id`, `started_at` DESC),
  INDEX `idx_sessions_pipeline_time` (`pipeline`, `started_at` DESC),
  CONSTRAINT `fk_sess_stream` FOREIGN KEY (`stream_id`) REFERENCES `sources`(`id`)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT `fk_sess_pipeline` FOREIGN KEY (`pipeline`) REFERENCES `pipelines`(`name`)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT `fk_sess_model` FOREIGN KEY (`model_id`) REFERENCES `models`(`id`)
    ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6) Events: lightweight operational events for observability
CREATE TABLE IF NOT EXISTS `events` (
  `id`        BIGINT       NOT NULL AUTO_INCREMENT,
  `ts`        DATETIME     NOT NULL,
  `level`     VARCHAR(16)  NOT NULL,
  `type`      VARCHAR(24)  NOT NULL,
  `pipeline`  VARCHAR(64)  NULL,
  `node`      VARCHAR(64)  NULL,
  `stream_id` VARCHAR(64)  NULL,
  `msg`       VARCHAR(256) NOT NULL,
  `extra`     JSON         NULL,
  PRIMARY KEY (`id`),
  INDEX `idx_events_ts` (`ts` DESC),
  INDEX `idx_events_pipeline_ts` (`pipeline`, `ts` DESC),
  CHECK (JSON_VALID(`extra`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7) Logs: verbose logs for analysis and debugging
CREATE TABLE IF NOT EXISTS `logs` (
  `id`        BIGINT       NOT NULL AUTO_INCREMENT,
  `ts`        DATETIME     NOT NULL,
  `level`     VARCHAR(16)  NOT NULL,
  `pipeline`  VARCHAR(64)  NULL,
  `node`      VARCHAR(64)  NULL,
  `stream_id` VARCHAR(64)  NULL,
  `message`   TEXT         NOT NULL,
  `extra`     JSON         NULL,
  PRIMARY KEY (`id`),
  INDEX `idx_logs_ts` (`ts` DESC),
  INDEX `idx_logs_pipeline_ts` (`pipeline`, `ts` DESC),
  CHECK (JSON_VALID(`extra`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- End of schema

