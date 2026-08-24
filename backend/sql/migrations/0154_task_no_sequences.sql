-- V15.4.1 待办任务号改为持久化序列表，保证删除任务后编号不回退、永不复用。
-- 之前基于 COUNT(*) 的生成在删除任务后会产生回退/复用，污染审计追踪。

CREATE TABLE IF NOT EXISTS task_no_sequences (
  assign_date DATE PRIMARY KEY,
  last_seq INT NOT NULL DEFAULT 0
);
