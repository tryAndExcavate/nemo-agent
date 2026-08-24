/*
Navicat MySQL Data Transfer

Source Server         : localhost_3306
Source Server Version : 80031
Source Host           : localhost:3306
Source Database       : ai_db

Target Server Type    : MYSQL
Target Server Version : 80031
File Encoding         : 65001

Date: 2026-08-21 19:47:38
*/

SET FOREIGN_KEY_CHECKS=0;

-- ----------------------------
-- Table structure for ai_file_info
-- ----------------------------
DROP TABLE IF EXISTS `ai_file_info`;
CREATE TABLE `ai_file_info` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `file_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '文件唯一标识',
  `file_name` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '原始文件名',
  `file_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '文件类型（pdf/doc/docx/txt/png/jpg等）',
  `file_size` bigint DEFAULT NULL COMMENT '文件大小（字节）',
  `minio_path` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT 'MinIO中的存储路径',
  `extracted_text` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '解析后的纯文本内容',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `conversation_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '会话ID（可选，用于关联特定会话）',
  `status` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT 'PENDING' COMMENT '文件状态：PENDING/PROCESSING/SUCCESS/FAILED',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `embed` tinyint DEFAULT NULL COMMENT '是否向量化',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_id` (`file_id`) USING BTREE,
  KEY `idx_conversation_id` (`conversation_id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2029891708835364876 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC COMMENT='文件元数据表，存储文件基本信息和解析后的内容';

-- ----------------------------
-- Table structure for ai_file_info_copy
-- ----------------------------
DROP TABLE IF EXISTS `ai_file_info_copy`;
CREATE TABLE `ai_file_info_copy` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `file_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '文件唯一标识',
  `file_name` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '原始文件名',
  `file_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '文件类型（pdf/doc/docx/txt/png/jpg等）',
  `file_size` bigint DEFAULT NULL COMMENT '文件大小（字节）',
  `minio_path` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT 'MinIO中的存储路径',
  `extracted_text` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '解析后的纯文本内容',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `conversation_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '会话ID（可选，用于关联特定会话）',
  `status` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT 'PENDING' COMMENT '文件状态：PENDING/PROCESSING/SUCCESS/FAILED',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `embed` tinyint DEFAULT NULL COMMENT '是否向量化',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `uk_file_id` (`file_id`) USING BTREE,
  KEY `idx_conversation_id` (`conversation_id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2029891708835364876 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC COMMENT='文件元数据表，存储文件基本信息和解析后的内容';

-- ----------------------------
-- Table structure for ai_ppt_inst
-- ----------------------------
DROP TABLE IF EXISTS `ai_ppt_inst`;
CREATE TABLE `ai_ppt_inst` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '实例ID',
  `conversation_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '会话ID',
  `template_code` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '选择的模板code',
  `status` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT 'INIT' COMMENT '状态',
  `query` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '用户原始需求',
  `requirement` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '需求澄清',
  `search_info` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '搜索信息',
  `outline` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '大纲',
  `ppt_schema` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT 'AI生成的PPT规划JSON',
  `file_url` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '生成的PPT文件URL',
  `error_msg` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '失败原因',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_conversation_id` (`conversation_id`) USING BTREE,
  KEY `idx_status` (`status`) USING BTREE,
  KEY `idx_template_code` (`template_code`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2030251353580011523 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='AI PPT生成实例表';

-- ----------------------------
-- Table structure for ai_ppt_template
-- ----------------------------
DROP TABLE IF EXISTS `ai_ppt_template`;
CREATE TABLE `ai_ppt_template` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '模板ID',
  `template_code` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '模板唯一编码',
  `template_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '模板名称',
  `template_desc` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci COMMENT '模板说明',
  `template_schema` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '模板结构JSON',
  `file_path` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT 'PPT模板文件路径',
  `style_tags` varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '风格标签：科技,商务,简约',
  `slide_count` int DEFAULT NULL COMMENT '模板页数',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE KEY `template_code` (`template_code`) USING BTREE,
  KEY `idx_template_code` (`template_code`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='AI PPT模板表';

-- ----------------------------
-- Table structure for ai_session
-- ----------------------------
DROP TABLE IF EXISTS `ai_session`;
CREATE TABLE `ai_session` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `session_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL COMMENT '会话ID',
  `question` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '用户问题',
  `answer` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT 'AI回复',
  `tools` varchar(1024) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '涉及的执行工具名称（逗号分隔）',
  `first_response_time` bigint DEFAULT NULL COMMENT '首次响应时间（毫秒）',
  `total_response_time` bigint DEFAULT NULL COMMENT '整体回复时间（毫秒）',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `reference` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '参考链接',
  `agent_type` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '智能体类型',
  `thinking` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci COMMENT '思考过程',
  `fileid` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '文件id',
  `recommend` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '推荐问题',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_session_id` (`session_id`) USING BTREE COMMENT '会话ID索引',
  KEY `idx_create_time` (`create_time`) USING BTREE COMMENT '创建时间索引'
) ENGINE=InnoDB AUTO_INCREMENT=2030594695312511068 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci ROW_FORMAT=DYNAMIC COMMENT='存储智能体与用户的对话历史，支持会话隔离和记忆功能';

-- ----------------------------
-- Table structure for archived_conversations
-- ----------------------------
DROP TABLE IF EXISTS `archived_conversations`;
CREATE TABLE `archived_conversations` (
  `session_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '归档记录主键ID',
  `user_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '用户ID',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '会话标题',
  `agent_type` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'agent类型',
  `archived_at` datetime NOT NULL COMMENT '归档时间',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '归档记录创建时间',
  `original_session_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '原会话id，对应conversations表的业务字符串id',
  PRIMARY KEY (`session_id`),
  KEY `idx_user` (`user_id`),
  KEY `idx_original_conv` (`original_session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='存储归档会话';

-- ----------------------------
-- Table structure for context_summaries
-- ----------------------------
DROP TABLE IF EXISTS `context_summaries`;
CREATE TABLE `context_summaries` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `conversation_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `summary_text` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `covered_up_to_message_id` bigint DEFAULT NULL,
  `token_count` int DEFAULT NULL,
  `summary_model_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_conversation` (`conversation_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------
-- Table structure for conversations
-- ----------------------------
DROP TABLE IF EXISTS `conversations`;
CREATE TABLE `conversations` (
  `session_id` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  `user_id` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '新对话',
  `agent_type` enum('active','archived') CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT 'active',
  `last_message_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`session_id`),
  KEY `idx_user_status_time` (`user_id`,`agent_type`,`last_message_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
