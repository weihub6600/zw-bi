-- V15.2 商品名称聚合 + 库存/库龄仅保留最新快照

CREATE TABLE IF NOT EXISTS product_name_aliases (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  product_id BIGINT NOT NULL,
  alias_name VARCHAR(255) NOT NULL,
  status ENUM('pending','accepted') NOT NULL DEFAULT 'pending',
  first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  seen_count BIGINT NOT NULL DEFAULT 1,
  resolved_at DATETIME NULL,
  resolved_by BIGINT NULL,
  UNIQUE KEY uk_product_alias (product_id,alias_name),
  KEY idx_product_alias_status (status,last_seen_at),
  CONSTRAINT fk_product_alias_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  CONSTRAINT fk_product_alias_user FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL
);

ALTER TABLE import_changes
  MODIFY COLUMN action ENUM('inserted','updated','deleted') NOT NULL;

-- 现有规范名称登记为已接受别名。
INSERT INTO product_name_aliases(product_id,alias_name,status,first_seen_at,last_seen_at,seen_count,resolved_at)
SELECT id,product_name,'accepted',NOW(),NOW(),1,NOW()
FROM products
ON DUPLICATE KEY UPDATE status='accepted',resolved_at=COALESCE(resolved_at,NOW());

-- 历史“同编码不同名称”不再作为硬错误展示；后续重新导入会按编码聚合。
UPDATE import_errors
SET severity='warning',
    error_code='PRODUCT_NAME_ALIAS_LEGACY',
    error_message=CONCAT('历史名称冲突已降级为别名提示；请重新导入有效数据并在商品名称聚合中确认规范名称。原提示：', error_message)
WHERE error_code IN ('PRODUCT_NAME_CONFLICT','PRODUCT_NAME_CONFLICT_IN_FILE');

-- 事实表只保留每个部门最新库存效期快照。
DROP TEMPORARY TABLE IF EXISTS tmp_bjr_latest_inventory;
CREATE TEMPORARY TABLE tmp_bjr_latest_inventory AS
SELECT department_id,MAX(snapshot_date) AS latest_date
FROM inventory_batch
GROUP BY department_id;
DELETE ib
FROM inventory_batch ib
JOIN tmp_bjr_latest_inventory latest ON latest.department_id=ib.department_id
WHERE ib.snapshot_date < latest.latest_date;
DROP TEMPORARY TABLE IF EXISTS tmp_bjr_latest_inventory;

-- 事实表只保留每个部门最新库龄快照。
DROP TEMPORARY TABLE IF EXISTS tmp_bjr_latest_aging;
CREATE TEMPORARY TABLE tmp_bjr_latest_aging AS
SELECT department_id,MAX(snapshot_date) AS latest_date
FROM aging_snapshot
GROUP BY department_id;
DELETE ag
FROM aging_snapshot ag
JOIN tmp_bjr_latest_aging latest ON latest.department_id=ag.department_id
WHERE ag.snapshot_date < latest.latest_date;
DROP TEMPORARY TABLE IF EXISTS tmp_bjr_latest_aging;
