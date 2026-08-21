-- V14.5 数据中心：导入记录与错误明细查询索引。
ALTER TABLE import_batches
  ADD INDEX idx_import_batches_dept_created (department_id,created_at);

ALTER TABLE import_errors
  ADD INDEX idx_import_errors_batch_severity (import_batch_id,severity,id);
