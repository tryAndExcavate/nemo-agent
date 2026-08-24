-- 消息编辑+重新生成+分支切换 - 数据库迁移脚本
-- 添加树形结构支持

-- ============================================
-- Phase 1: 修改 ai_session 表
-- ============================================

-- 添加树形结构字段
ALTER TABLE `ai_session`
  ADD COLUMN `parent_id` bigint DEFAULT NULL
      COMMENT '父轮次ID（对应本表id），NULL表示该会话的第一轮对话' AFTER `session_id`,
  ADD COLUMN `branch_order` int NOT NULL DEFAULT 1
      COMMENT '分支顺序（同一父消息下的分支编号）' AFTER `parent_id`,
  ADD COLUMN `is_active_branch` tinyint(1) NOT NULL DEFAULT 1
      COMMENT '是否在当前激活分支路径上：1=是，0=已被切换掉的历史分支' AFTER `branch_order`,
  ADD COLUMN `original_message_id` bigint DEFAULT NULL
      COMMENT '若本轮是编辑/重新生成产生的新分支，记录原始轮次id，便于追溯' AFTER `is_active_branch`,
  ADD COLUMN `model_id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci DEFAULT NULL
      COMMENT '生成本轮回答所使用的模型ID，对应可插拔基座的模型配置id' AFTER `agent_type`,
  ADD COLUMN `token_count` int DEFAULT NULL
      COMMENT '本轮问答（question+answer）的token总数，供上下文压缩预算计算使用' AFTER `total_response_time`;

-- 添加索引
CREATE INDEX `idx_session_parent` ON `ai_session` (`parent_id`) USING BTREE;
CREATE INDEX `idx_session_original` ON `ai_session` (`original_message_id`) USING BTREE;
CREATE INDEX `idx_session_active` ON `ai_session` (`session_id`, `is_active_branch`) USING BTREE;
CREATE INDEX `idx_session_branch` ON `ai_session` (`parent_id`, `branch_order`) USING BTREE;

-- ============================================
-- Phase 2: 修改 conversations 表
-- ============================================

-- 添加分支状态跟踪字段
ALTER TABLE `conversations`
  ADD COLUMN `active_head_id` bigint DEFAULT NULL
      COMMENT '激活分支的最新消息ID，对应ai_session.id' AFTER `title`;

-- ============================================
-- Phase 3: 数据迁移
-- ============================================

-- 为现有消息设置parent_id链（按session_id和create_time ASC排列）
-- 每条消息的parent_id指向同一会话中前一条消息的id
UPDATE ai_session a
SET parent_id = (
    SELECT MAX(id) FROM ai_session b
    WHERE b.session_id = a.session_id
    AND b.create_time < a.create_time
)
WHERE parent_id IS NULL;

-- 设置branch_order和is_active_branch（现有消息都是主线分支）
UPDATE ai_session SET branch_order = 1, is_active_branch = TRUE;

-- 更新conversations的active_head_id（指向每个会话的最新消息）
UPDATE conversations c
SET active_head_id = (
    SELECT MAX(id) FROM ai_session a
    WHERE a.session_id = c.session_id
    AND a.is_active_branch = TRUE
);

-- ============================================
-- 验证查询
-- ============================================

-- 查看ai_session表的新字段
-- SELECT id, session_id, parent_id, branch_order, is_active_branch, original_message_id, model_id, token_count
-- FROM ai_session
-- LIMIT 10;

-- 查看conversations表的新字段
-- SELECT session_id, title, active_head_id
-- FROM conversations
-- LIMIT 10;
