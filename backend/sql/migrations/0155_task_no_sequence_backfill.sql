-- V15.4.1 回填 task_no_sequences 历史最大序号。
-- 修复：升级前已存在的历史任务编号（如 TD20260824-001~018）未进入序列表，
-- 否则新分配会从 001 重新开始，撞 todo_tasks.task_no UNIQUE。
-- 幂等：按 assign_date 取历史最大后缀，仅当序列表缺失该日期时才回填。

INSERT INTO task_no_sequences (assign_date, last_seq)
SELECT t.assign_date, MAX(CAST(SUBSTRING_INDEX(t.task_no, '-', -1) AS UNSIGNED))
FROM todo_tasks t
WHERE t.task_no LIKE 'TD%'
  AND t.assign_date IS NOT NULL
GROUP BY t.assign_date
ON DUPLICATE KEY UPDATE
  last_seq = GREATEST(task_no_sequences.last_seq, VALUES(last_seq));
