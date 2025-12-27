-- MySQL dump 10.13  Distrib 8.4.7, for Linux (x86_64)
--
-- Host: localhost    Database: cv_cp
-- ------------------------------------------------------
-- Server version	8.4.7

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `events`
--

DROP TABLE IF EXISTS `events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `events` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `ts` datetime NOT NULL,
  `level` varchar(16) NOT NULL,
  `type` varchar(24) NOT NULL,
  `pipeline` varchar(64) DEFAULT NULL,
  `node` varchar(64) DEFAULT NULL,
  `stream_id` varchar(64) DEFAULT NULL,
  `msg` varchar(256) NOT NULL,
  `extra` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_events_ts` (`ts` DESC),
  KEY `idx_events_pipeline_ts` (`pipeline`,`ts` DESC),
  KEY `idx_events_stream_ts` (`stream_id`,`ts` DESC),
  KEY `idx_events_node_ts` (`node`,`ts` DESC),
  CONSTRAINT `events_chk_1` CHECK (json_valid(`extra`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `events`
--

LOCK TABLES `events` WRITE;
/*!40000 ALTER TABLE `events` DISABLE KEYS */;
/*!40000 ALTER TABLE `events` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `graphs`
--

DROP TABLE IF EXISTS `graphs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `graphs` (
  `id` varchar(64) NOT NULL,
  `name` varchar(128) NOT NULL,
  `requires` json DEFAULT NULL,
  `file_path` varchar(512) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `graphs_chk_1` CHECK (json_valid(`requires`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `graphs`
--

LOCK TABLES `graphs` WRITE;
/*!40000 ALTER TABLE `graphs` DISABLE KEYS */;
/*!40000 ALTER TABLE `graphs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `logs`
--

DROP TABLE IF EXISTS `logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `logs` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `ts` datetime NOT NULL,
  `level` varchar(16) NOT NULL,
  `pipeline` varchar(64) DEFAULT NULL,
  `node` varchar(64) DEFAULT NULL,
  `stream_id` varchar(64) DEFAULT NULL,
  `message` text NOT NULL,
  `extra` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_logs_ts` (`ts` DESC),
  KEY `idx_logs_pipeline_ts` (`pipeline`,`ts` DESC),
  KEY `idx_logs_stream_ts` (`stream_id`,`ts` DESC),
  KEY `idx_logs_node_ts` (`node`,`ts` DESC),
  CONSTRAINT `logs_chk_1` CHECK (json_valid(`extra`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `logs`
--

LOCK TABLES `logs` WRITE;
/*!40000 ALTER TABLE `logs` DISABLE KEYS */;
/*!40000 ALTER TABLE `logs` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `m_cities`
--

DROP TABLE IF EXISTS `m_cities`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `m_cities` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(64) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `m_cities`
--

LOCK TABLES `m_cities` WRITE;
/*!40000 ALTER TABLE `m_cities` DISABLE KEYS */;
INSERT INTO `m_cities` VALUES (1,'åŒ—äº¬'),(2,'ä¸Šæµ·'),(3,'æ·±åœ³');
/*!40000 ALTER TABLE `m_cities` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `m_customers`
--

DROP TABLE IF EXISTS `m_customers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `m_customers` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(64) NOT NULL,
  `city_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_mcust_city` (`city_id`),
  CONSTRAINT `fk_mcust_city` FOREIGN KEY (`city_id`) REFERENCES `m_cities` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `m_customers`
--

LOCK TABLES `m_customers` WRITE;
/*!40000 ALTER TABLE `m_customers` DISABLE KEYS */;
INSERT INTO `m_customers` VALUES (1,'ç”¨æˆ·A',1),(2,'ç”¨æˆ·B',1),(3,'ç”¨æˆ·C',2),(4,'ç”¨æˆ·D',3);
/*!40000 ALTER TABLE `m_customers` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `m_orders`
--

DROP TABLE IF EXISTS `m_orders`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `m_orders` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `customer_id` bigint NOT NULL,
  `created_at` datetime NOT NULL,
  `amount` decimal(10,2) NOT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_mord_customer` (`customer_id`),
  CONSTRAINT `fk_mord_customer` FOREIGN KEY (`customer_id`) REFERENCES `m_customers` (`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=193 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `m_orders`
--

LOCK TABLES `m_orders` WRITE;
/*!40000 ALTER TABLE `m_orders` DISABLE KEYS */;
INSERT INTO `m_orders` VALUES (1,1,'2023-01-05 00:00:00',150.00,'paid'),(2,1,'2023-01-15 00:00:00',200.00,'paid'),(3,1,'2023-02-08 00:00:00',180.00,'paid'),(4,1,'2023-02-20 00:00:00',220.00,'paid'),(5,1,'2023-03-10 00:00:00',300.00,'paid'),(6,1,'2023-03-25 00:00:00',150.00,'paid'),(7,1,'2023-04-05 00:00:00',280.00,'paid'),(8,1,'2023-04-18 00:00:00',190.00,'paid'),(9,1,'2023-05-12 00:00:00',350.00,'paid'),(10,1,'2023-05-28 00:00:00',200.00,'paid'),(11,1,'2023-06-03 00:00:00',420.00,'paid'),(12,1,'2023-06-22 00:00:00',180.00,'paid'),(13,1,'2023-07-08 00:00:00',290.00,'paid'),(14,1,'2023-07-19 00:00:00',310.00,'paid'),(15,1,'2023-08-14 00:00:00',380.00,'paid'),(16,1,'2023-08-26 00:00:00',150.00,'paid'),(17,1,'2023-09-09 00:00:00',270.00,'paid'),(18,1,'2023-09-21 00:00:00',340.00,'paid'),(19,1,'2023-10-05 00:00:00',450.00,'paid'),(20,1,'2023-10-18 00:00:00',220.00,'paid'),(21,1,'2023-11-11 00:00:00',380.00,'paid'),(22,1,'2023-11-25 00:00:00',290.00,'paid'),(23,1,'2023-12-08 00:00:00',520.00,'paid'),(24,1,'2023-12-20 00:00:00',180.00,'paid'),(25,1,'2024-01-10 00:00:00',320.00,'paid'),(26,1,'2024-01-22 00:00:00',280.00,'paid'),(27,1,'2024-02-05 00:00:00',190.00,'paid'),(28,1,'2024-02-18 00:00:00',350.00,'paid'),(29,1,'2024-03-12 00:00:00',420.00,'paid'),(30,1,'2024-03-28 00:00:00',180.00,'paid'),(31,1,'2024-04-08 00:00:00',380.00,'paid'),(32,1,'2024-04-21 00:00:00',290.00,'paid'),(33,1,'2024-05-15 00:00:00',450.00,'paid'),(34,1,'2024-05-29 00:00:00',200.00,'paid'),(35,1,'2024-06-06 00:00:00',520.00,'paid'),(36,1,'2024-06-19 00:00:00',310.00,'paid'),(37,1,'2024-07-03 00:00:00',380.00,'paid'),(38,1,'2024-07-16 00:00:00',270.00,'paid'),(39,1,'2024-08-09 00:00:00',420.00,'paid'),(40,1,'2024-08-25 00:00:00',190.00,'paid'),(41,1,'2024-09-11 00:00:00',350.00,'paid'),(42,1,'2024-09-24 00:00:00',280.00,'paid'),(43,1,'2024-10-07 00:00:00',480.00,'paid'),(44,1,'2024-10-20 00:00:00',220.00,'paid'),(45,1,'2024-11-04 00:00:00',390.00,'paid'),(46,1,'2024-11-17 00:00:00',310.00,'paid'),(47,1,'2024-12-02 00:00:00',550.00,'paid'),(48,1,'2024-12-15 00:00:00',280.00,'paid'),(49,2,'2023-01-08 00:00:00',280.00,'paid'),(50,2,'2023-01-20 00:00:00',350.00,'paid'),(51,2,'2023-02-12 00:00:00',420.00,'paid'),(52,2,'2023-02-25 00:00:00',180.00,'paid'),(53,2,'2023-03-05 00:00:00',380.00,'paid'),(54,2,'2023-03-18 00:00:00',290.00,'paid'),(55,2,'2023-04-10 00:00:00',450.00,'paid'),(56,2,'2023-04-23 00:00:00',200.00,'paid'),(57,2,'2023-05-08 00:00:00',520.00,'paid'),(58,2,'2023-05-21 00:00:00',310.00,'paid'),(59,2,'2023-06-15 00:00:00',380.00,'paid'),(60,2,'2023-06-28 00:00:00',420.00,'paid'),(61,2,'2023-07-12 00:00:00',290.00,'paid'),(62,2,'2023-07-25 00:00:00',350.00,'paid'),(63,2,'2023-08-05 00:00:00',480.00,'paid'),(64,2,'2023-08-18 00:00:00',220.00,'paid'),(65,2,'2023-09-10 00:00:00',390.00,'paid'),(66,2,'2023-09-23 00:00:00',310.00,'paid'),(67,2,'2023-10-08 00:00:00',520.00,'paid'),(68,2,'2023-10-21 00:00:00',280.00,'paid'),(69,2,'2023-11-05 00:00:00',450.00,'paid'),(70,2,'2023-11-18 00:00:00',380.00,'paid'),(71,2,'2023-12-10 00:00:00',580.00,'paid'),(72,2,'2023-12-23 00:00:00',320.00,'paid'),(73,2,'2024-01-15 00:00:00',420.00,'paid'),(74,2,'2024-01-28 00:00:00',380.00,'paid'),(75,2,'2024-02-08 00:00:00',350.00,'paid'),(76,2,'2024-02-21 00:00:00',290.00,'paid'),(77,2,'2024-03-05 00:00:00',480.00,'paid'),(78,2,'2024-03-18 00:00:00',220.00,'paid'),(79,2,'2024-04-12 00:00:00',520.00,'paid'),(80,2,'2024-04-25 00:00:00',310.00,'paid'),(81,2,'2024-05-08 00:00:00',580.00,'paid'),(82,2,'2024-05-21 00:00:00',420.00,'paid'),(83,2,'2024-06-14 00:00:00',450.00,'paid'),(84,2,'2024-06-27 00:00:00',380.00,'paid'),(85,2,'2024-07-10 00:00:00',520.00,'paid'),(86,2,'2024-07-23 00:00:00',290.00,'paid'),(87,2,'2024-08-06 00:00:00',480.00,'paid'),(88,2,'2024-08-19 00:00:00',350.00,'paid'),(89,2,'2024-09-02 00:00:00',420.00,'paid'),(90,2,'2024-09-15 00:00:00',310.00,'paid'),(91,2,'2024-10-08 00:00:00',550.00,'paid'),(92,2,'2024-10-21 00:00:00',280.00,'paid'),(93,2,'2024-11-04 00:00:00',480.00,'paid'),(94,2,'2024-11-17 00:00:00',390.00,'paid'),(95,2,'2024-12-09 00:00:00',620.00,'paid'),(96,2,'2024-12-22 00:00:00',350.00,'paid'),(97,3,'2023-01-12 00:00:00',220.00,'paid'),(98,3,'2023-01-25 00:00:00',180.00,'paid'),(99,3,'2023-02-08 00:00:00',290.00,'paid'),(100,3,'2023-02-21 00:00:00',150.00,'paid'),(101,3,'2023-03-15 00:00:00',350.00,'paid'),(102,3,'2023-03-28 00:00:00',200.00,'paid'),(103,3,'2023-04-10 00:00:00',280.00,'paid'),(104,3,'2023-04-23 00:00:00',320.00,'paid'),(105,3,'2023-05-18 00:00:00',380.00,'paid'),(106,3,'2023-05-31 00:00:00',250.00,'paid'),(107,3,'2023-06-12 00:00:00',420.00,'paid'),(108,3,'2023-06-25 00:00:00',190.00,'paid'),(109,3,'2023-07-08 00:00:00',350.00,'paid'),(110,3,'2023-07-21 00:00:00',280.00,'paid'),(111,3,'2023-08-14 00:00:00',310.00,'paid'),(112,3,'2023-08-27 00:00:00',220.00,'paid'),(113,3,'2023-09-10 00:00:00',380.00,'paid'),(114,3,'2023-09-23 00:00:00',290.00,'paid'),(115,3,'2023-10-05 00:00:00',450.00,'paid'),(116,3,'2023-10-18 00:00:00',200.00,'paid'),(117,3,'2023-11-12 00:00:00',320.00,'paid'),(118,3,'2023-11-25 00:00:00',380.00,'paid'),(119,3,'2023-12-08 00:00:00',480.00,'paid'),(120,3,'2023-12-21 00:00:00',250.00,'paid'),(121,3,'2024-01-15 00:00:00',350.00,'paid'),(122,3,'2024-01-28 00:00:00',280.00,'paid'),(123,3,'2024-02-10 00:00:00',320.00,'paid'),(124,3,'2024-02-23 00:00:00',190.00,'paid'),(125,3,'2024-03-08 00:00:00',420.00,'paid'),(126,3,'2024-03-21 00:00:00',250.00,'paid'),(127,3,'2024-04-14 00:00:00',380.00,'paid'),(128,3,'2024-04-27 00:00:00',310.00,'paid'),(129,3,'2024-05-10 00:00:00',450.00,'paid'),(130,3,'2024-05-23 00:00:00',280.00,'paid'),(131,3,'2024-06-06 00:00:00',520.00,'paid'),(132,3,'2024-06-19 00:00:00',350.00,'paid'),(133,3,'2024-07-12 00:00:00',380.00,'paid'),(134,3,'2024-07-25 00:00:00',290.00,'paid'),(135,3,'2024-08-08 00:00:00',450.00,'paid'),(136,3,'2024-08-21 00:00:00',220.00,'paid'),(137,3,'2024-09-14 00:00:00',380.00,'paid'),(138,3,'2024-09-27 00:00:00',310.00,'paid'),(139,3,'2024-10-10 00:00:00',520.00,'paid'),(140,3,'2024-10-23 00:00:00',250.00,'paid'),(141,3,'2024-11-06 00:00:00',420.00,'paid'),(142,3,'2024-11-19 00:00:00',380.00,'paid'),(143,3,'2024-12-12 00:00:00',550.00,'paid'),(144,3,'2024-12-25 00:00:00',320.00,'paid'),(145,4,'2023-01-10 00:00:00',180.00,'paid'),(146,4,'2023-01-23 00:00:00',250.00,'paid'),(147,4,'2023-02-15 00:00:00',320.00,'paid'),(148,4,'2023-02-28 00:00:00',190.00,'paid'),(149,4,'2023-03-12 00:00:00',280.00,'paid'),(150,4,'2023-03-25 00:00:00',350.00,'paid'),(151,4,'2023-04-08 00:00:00',220.00,'paid'),(152,4,'2023-04-21 00:00:00',290.00,'paid'),(153,4,'2023-05-15 00:00:00',380.00,'paid'),(154,4,'2023-05-28 00:00:00',200.00,'paid'),(155,4,'2023-06-10 00:00:00',450.00,'paid'),(156,4,'2023-06-23 00:00:00',310.00,'paid'),(157,4,'2023-07-18 00:00:00',280.00,'paid'),(158,4,'2023-07-31 00:00:00',350.00,'paid'),(159,4,'2023-08-12 00:00:00',420.00,'paid'),(160,4,'2023-08-25 00:00:00',190.00,'paid'),(161,4,'2023-09-08 00:00:00',350.00,'paid'),(162,4,'2023-09-21 00:00:00',280.00,'paid'),(163,4,'2023-10-15 00:00:00',480.00,'paid'),(164,4,'2023-10-28 00:00:00',220.00,'paid'),(165,4,'2023-11-10 00:00:00',390.00,'paid'),(166,4,'2023-11-23 00:00:00',310.00,'paid'),(167,4,'2023-12-05 00:00:00',520.00,'paid'),(168,4,'2023-12-18 00:00:00',280.00,'paid'),(169,4,'2024-01-12 00:00:00',350.00,'paid'),(170,4,'2024-01-25 00:00:00',290.00,'paid'),(171,4,'2024-02-08 00:00:00',280.00,'paid'),(172,4,'2024-02-21 00:00:00',350.00,'paid'),(173,4,'2024-03-15 00:00:00',420.00,'paid'),(174,4,'2024-03-28 00:00:00',190.00,'paid'),(175,4,'2024-04-10 00:00:00',380.00,'paid'),(176,4,'2024-04-23 00:00:00',280.00,'paid'),(177,4,'2024-05-18 00:00:00',450.00,'paid'),(178,4,'2024-05-31 00:00:00',320.00,'paid'),(179,4,'2024-06-12 00:00:00',520.00,'paid'),(180,4,'2024-06-25 00:00:00',280.00,'paid'),(181,4,'2024-07-08 00:00:00',390.00,'paid'),(182,4,'2024-07-21 00:00:00',350.00,'paid'),(183,4,'2024-08-14 00:00:00',480.00,'paid'),(184,4,'2024-08-27 00:00:00',220.00,'paid'),(185,4,'2024-09-10 00:00:00',420.00,'paid'),(186,4,'2024-09-23 00:00:00',310.00,'paid'),(187,4,'2024-10-05 00:00:00',550.00,'paid'),(188,4,'2024-10-18 00:00:00',280.00,'paid'),(189,4,'2024-11-12 00:00:00',480.00,'paid'),(190,4,'2024-11-25 00:00:00',350.00,'paid'),(191,4,'2024-12-08 00:00:00',620.00,'paid'),(192,4,'2024-12-21 00:00:00',380.00,'paid');
/*!40000 ALTER TABLE `m_orders` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `models`
--

DROP TABLE IF EXISTS `models`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `models` (
  `id` varchar(128) NOT NULL,
  `task` varchar(32) DEFAULT NULL,
  `family` varchar(64) DEFAULT NULL,
  `variant` varchar(64) DEFAULT NULL,
  `path` varchar(512) DEFAULT NULL,
  `conf` double DEFAULT NULL,
  `iou` double DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `models`
--

LOCK TABLES `models` WRITE;
/*!40000 ALTER TABLE `models` DISABLE KEYS */;
/*!40000 ALTER TABLE `models` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `pipelines`
--

DROP TABLE IF EXISTS `pipelines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `pipelines` (
  `name` varchar(64) NOT NULL,
  `graph_id` varchar(64) DEFAULT NULL,
  `default_model_id` varchar(128) DEFAULT NULL,
  `encoder_cfg` json DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`name`),
  CONSTRAINT `pipelines_chk_1` CHECK (json_valid(`encoder_cfg`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `pipelines`
--

LOCK TABLES `pipelines` WRITE;
/*!40000 ALTER TABLE `pipelines` DISABLE KEYS */;
INSERT INTO `pipelines` VALUES ('agent_demo','graph_demo','model_demo',NULL,'2025-11-24 16:32:16','2025-11-24 16:32:16'),('p1',NULL,NULL,NULL,'2025-11-25 13:13:14','2025-11-25 13:13:14');
/*!40000 ALTER TABLE `pipelines` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sessions`
--

DROP TABLE IF EXISTS `sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sessions` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `stream_id` varchar(64) NOT NULL,
  `pipeline` varchar(64) NOT NULL,
  `model_id` varchar(128) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  `error_msg` varchar(256) DEFAULT NULL,
  `started_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `stopped_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_sessions_stream_time` (`stream_id`,`started_at` DESC),
  KEY `idx_sessions_pipeline_time` (`pipeline`,`started_at` DESC),
  KEY `fk_sess_model` (`model_id`),
  CONSTRAINT `fk_sess_model` FOREIGN KEY (`model_id`) REFERENCES `models` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_sess_pipeline` FOREIGN KEY (`pipeline`) REFERENCES `pipelines` (`name`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_sess_stream` FOREIGN KEY (`stream_id`) REFERENCES `sources` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sessions`
--

LOCK TABLES `sessions` WRITE;
/*!40000 ALTER TABLE `sessions` DISABLE KEYS */;
/*!40000 ALTER TABLE `sessions` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `sources`
--

DROP TABLE IF EXISTS `sources`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sources` (
  `id` varchar(64) NOT NULL,
  `uri` varchar(1024) NOT NULL,
  `status` varchar(32) NOT NULL DEFAULT 'Unknown',
  `caps` json DEFAULT NULL,
  `fps` double DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_sources_status` (`status`),
  KEY `idx_sources_updated` (`updated_at`),
  CONSTRAINT `sources_chk_1` CHECK (json_valid(`caps`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sources`
--

LOCK TABLES `sources` WRITE;
/*!40000 ALTER TABLE `sources` DISABLE KEYS */;
/*!40000 ALTER TABLE `sources` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `train_jobs`
--

DROP TABLE IF EXISTS `train_jobs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `train_jobs` (
  `id` varchar(64) NOT NULL,
  `status` varchar(24) NOT NULL,
  `phase` varchar(24) DEFAULT NULL,
  `cfg` json DEFAULT NULL,
  `mlflow_run_id` varchar(64) DEFAULT NULL,
  `registered_model` varchar(128) DEFAULT NULL,
  `registered_version` int DEFAULT NULL,
  `metrics` json DEFAULT NULL,
  `artifacts` json DEFAULT NULL,
  `error` varchar(512) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_train_jobs_status_time` (`status`,`updated_at` DESC),
  CONSTRAINT `train_jobs_chk_1` CHECK (json_valid(`cfg`)),
  CONSTRAINT `train_jobs_chk_2` CHECK (json_valid(`metrics`)),
  CONSTRAINT `train_jobs_chk_3` CHECK (json_valid(`artifacts`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `train_jobs`
--

LOCK TABLES `train_jobs` WRITE;
/*!40000 ALTER TABLE `train_jobs` DISABLE KEYS */;
/*!40000 ALTER TABLE `train_jobs` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-12-27 13:42:20
