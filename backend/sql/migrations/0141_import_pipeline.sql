ALTER TABLE products
  ADD COLUMN IF NOT EXISTS import_batch_id BIGINT NULL COMMENT '最后一次商品资料导入批次；用于安全回滚' AFTER barcode;

ALTER TABLE import_batches
  DROP INDEX uk_import_hash_scope;

CREATE INDEX idx_import_hash_scope
  ON import_batches(department_id,data_type,business_date,file_sha256);

CREATE INDEX idx_shop_name ON shops(source_name);
CREATE INDEX idx_wh_name ON warehouses(source_name);

CREATE TABLE IF NOT EXISTS import_changes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  import_batch_id BIGINT NOT NULL,
  table_name VARCHAR(64) NOT NULL,
  row_pk BIGINT NOT NULL,
  action ENUM('inserted','updated') NOT NULL,
  before_data JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_import_changes_batch (import_batch_id,id),
  CONSTRAINT fk_import_change_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(id)
);

ALTER TABLE import_batches
  ADD COLUMN IF NOT EXISTS warning_rows INT NOT NULL DEFAULT 0 AFTER error_rows;

ALTER TABLE import_errors
  ADD COLUMN IF NOT EXISTS severity ENUM('error','warning') NOT NULL DEFAULT 'error' AFTER row_no;
