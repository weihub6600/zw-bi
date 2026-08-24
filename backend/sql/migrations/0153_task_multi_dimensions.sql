-- V15.4.1 待办任务店铺/仓库改为多对多关系。
-- 新增 task_shops / task_warehouses 关联表，并将已有单值 shop_id/warehouse_id 安全迁移。
-- 保留 todo_tasks.shop_id / warehouse_id 作为向后兼容（旧字段），不删除历史数据。

CREATE TABLE IF NOT EXISTS task_shops (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  task_id BIGINT NOT NULL,
  shop_id BIGINT NOT NULL,
  UNIQUE KEY uk_task_shop (task_id, shop_id),
  KEY idx_task_shops_shop (shop_id),
  CONSTRAINT fk_task_shops_task FOREIGN KEY (task_id) REFERENCES todo_tasks(id) ON DELETE CASCADE,
  CONSTRAINT fk_task_shops_shop FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_warehouses (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  task_id BIGINT NOT NULL,
  warehouse_id BIGINT NOT NULL,
  UNIQUE KEY uk_task_warehouse (task_id, warehouse_id),
  KEY idx_task_warehouses_warehouse (warehouse_id),
  CONSTRAINT fk_task_warehouses_task FOREIGN KEY (task_id) REFERENCES todo_tasks(id) ON DELETE CASCADE,
  CONSTRAINT fk_task_warehouses_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE
);

-- 迁移旧数据：原 shop_id -> task_shops（幂等，重复执行不会产生重复行）
INSERT IGNORE INTO task_shops (task_id, shop_id)
SELECT id, shop_id FROM todo_tasks WHERE shop_id IS NOT NULL;

-- 迁移旧数据：原 warehouse_id -> task_warehouses
INSERT IGNORE INTO task_warehouses (task_id, warehouse_id)
SELECT id, warehouse_id FROM todo_tasks WHERE warehouse_id IS NOT NULL;
