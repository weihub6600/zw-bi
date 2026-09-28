-- Department-scoped, effective-dated product cost versions.
-- This migration intentionally does not alter products or historical migrations.
CREATE TABLE IF NOT EXISTS department_product_costs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  department_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  effective_date DATE NOT NULL,
  unit_cost DECIMAL(18,6) NOT NULL,
  currency VARCHAR(16) NULL,
  unit VARCHAR(32) NULL,
  source ENUM('manual','product_import') NOT NULL DEFAULT 'manual',
  source_import_batch_id BIGINT NULL,
  created_by BIGINT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_department_product_cost_date (department_id,product_id,effective_date),
  KEY idx_department_product_cost_lookup (department_id,product_id,effective_date),
  KEY idx_department_product_cost_batch (source_import_batch_id),
  CONSTRAINT fk_cost_department FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_cost_product FOREIGN KEY (product_id) REFERENCES products(id),
  CONSTRAINT fk_cost_creator FOREIGN KEY (created_by) REFERENCES users(id),
  CONSTRAINT fk_cost_import_batch FOREIGN KEY (source_import_batch_id) REFERENCES import_batches(id) ON DELETE SET NULL
);
