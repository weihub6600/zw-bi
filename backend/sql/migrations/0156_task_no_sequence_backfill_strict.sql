-- V15.4.1 严格回填 task_no_sequences 历史最大序号（REGEXP 加固）。
-- 0155 使用 LIKE 'TD%' 可能误匹配非标准 task_no（如 TDabc），导致 CAST 产生 0。
-- 本迁移用严格正则 ^TD[0-9]{8}-[0-9]+$ 重新回填，GREATEST 幂等，不会降低已有序号。

INSERT INTO task_no_sequences (assign_date, last_seq)
SELECT t.assign_date, MAX(CAST(SUBSTRING_INDEX(t.task_no, '-', -1) AS UNSIGNED))
FROM todo_tasks t
WHERE t.task_no REGEXP '^TD[0-9]{8}-[0-9]+$'
  AND t.assign_date IS NOT NULL
GROUP BY t.assign_date
ON DUPLICATE KEY UPDATE
  last_seq = GREATEST(task_no_sequences.last_seq, VALUES(last_seq));
