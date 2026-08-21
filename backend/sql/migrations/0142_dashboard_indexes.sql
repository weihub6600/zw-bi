-- V14.2 Dashboard 聚合查询索引。
-- 如索引已经存在，请忽略 MySQL Duplicate key name 错误。
ALTER TABLE inventory_batch
  ADD INDEX idx_inventory_dept_snapshot (department_id, snapshot_date);

ALTER TABLE aging_snapshot
  ADD INDEX idx_aging_dept_snapshot (department_id, snapshot_date),
  ADD INDEX idx_aging_product_snapshot (product_id, snapshot_date);
