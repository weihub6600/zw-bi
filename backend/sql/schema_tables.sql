
CREATE TABLE IF NOT EXISTS schema_migrations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  migration_id VARCHAR(128) NOT NULL UNIQUE,
  app_version VARCHAR(32) NULL,
  checksum CHAR(64) NOT NULL,
  applied_by VARCHAR(64) NOT NULL DEFAULT 'release_tool',
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS release_history (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  app_version VARCHAR(32) NOT NULL,
  from_version VARCHAR(32) NULL,
  action ENUM('install','upgrade','rollback') NOT NULL,
  status ENUM('success','failed') NOT NULL,
  db_backup_path VARCHAR(500) NULL,
  note VARCHAR(1000) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_release_history_created (created_at),
  KEY idx_release_history_version (app_version, created_at)
);

CREATE TABLE IF NOT EXISTS departments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  code VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(128) NOT NULL UNIQUE,
  status ENUM('enabled','disabled') NOT NULL DEFAULT 'enabled',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id VARCHAR(32) NOT NULL UNIQUE COMMENT '业务用户ID，永久不可修改、不复用',
  username VARCHAR(128) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  is_system_admin TINYINT(1) NOT NULL DEFAULT 0,
  status ENUM('enabled','disabled') NOT NULL DEFAULT 'enabled',
  last_login_time DATETIME NULL,
  last_active_time DATETIME NULL,
  login_count BIGINT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS auth_sessions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_pk BIGINT NOT NULL,
  session_token_hash CHAR(64) NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ip_address VARCHAR(64) NULL,
  user_agent VARCHAR(1000) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_auth_session_user (user_pk,expires_at),
  KEY idx_auth_session_expiry (expires_at),
  CONSTRAINT fk_auth_session_user FOREIGN KEY (user_pk) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_departments (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_pk BIGINT NOT NULL,
  department_id BIGINT NOT NULL,
  role ENUM('dept_admin','member') NOT NULL,
  status ENUM('enabled','disabled') NOT NULL DEFAULT 'enabled',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_department (user_pk, department_id),
  CONSTRAINT fk_ud_user FOREIGN KEY (user_pk) REFERENCES users(id),
  CONSTRAINT fk_ud_department FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE IF NOT EXISTS products (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  merchant_code VARCHAR(128) NOT NULL UNIQUE,
  product_name VARCHAR(255) NOT NULL,
  spec VARCHAR(255) NULL,
  brand VARCHAR(128) NULL,
  category VARCHAR(128) NULL,
  barcode VARCHAR(128) NULL,
  import_batch_id BIGINT NULL COMMENT '最后一次商品资料导入批次；用于安全回滚',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_categories (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  category_name VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_product_category_name (category_name)
);

CREATE TABLE IF NOT EXISTS product_category_relations (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  product_id BIGINT NOT NULL,
  category_id BIGINT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_product_category (product_id,category_id),
  KEY idx_product_category_product (product_id),
  KEY idx_product_category_category (category_id),
  CONSTRAINT fk_product_category_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  CONSTRAINT fk_product_category_category FOREIGN KEY (category_id) REFERENCES product_categories(id) ON DELETE CASCADE
);

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

CREATE TABLE IF NOT EXISTS shops (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  source_code VARCHAR(128) NULL,
  source_name VARCHAR(255) NOT NULL,
  UNIQUE KEY uk_shop_source (source_code, source_name),
  KEY idx_shop_name (source_name)
);

CREATE TABLE IF NOT EXISTS warehouses (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  source_code VARCHAR(128) NULL,
  source_name VARCHAR(255) NOT NULL,
  UNIQUE KEY uk_wh_source (source_code, source_name),
  KEY idx_wh_name (source_name)
);

CREATE TABLE IF NOT EXISTS sales_daily (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  department_id BIGINT NOT NULL,
  business_date DATE NOT NULL,
  shop_id BIGINT NOT NULL,
  warehouse_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  sales_qty DECIMAL(18,4) NOT NULL DEFAULT 0,
  avg_price DECIMAL(18,6) NULL,
  import_batch_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_sales_daily (department_id,business_date,shop_id,warehouse_id,product_id),
  KEY idx_sales_product_date (product_id,business_date),
  KEY idx_sales_dept_date (department_id,business_date),
  CONSTRAINT fk_sales_dept FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_sales_shop FOREIGN KEY (shop_id) REFERENCES shops(id),
  CONSTRAINT fk_sales_wh FOREIGN KEY (warehouse_id) REFERENCES warehouses(id),
  CONSTRAINT fk_sales_product FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS inventory_batch (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  department_id BIGINT NOT NULL,
  snapshot_date DATE NOT NULL,
  warehouse_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  stock_qty DECIMAL(18,4) NOT NULL DEFAULT 0,
  production_date DATE NULL,
  expire_date DATE NULL,
  import_batch_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_inventory_batch (department_id,snapshot_date,warehouse_id,product_id,production_date,expire_date),
  KEY idx_inventory_product_snapshot (product_id,snapshot_date),
  KEY idx_inventory_dept_snapshot (department_id,snapshot_date),
  CONSTRAINT fk_inv_dept FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_inv_wh FOREIGN KEY (warehouse_id) REFERENCES warehouses(id),
  CONSTRAINT fk_inv_product FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS aging_snapshot (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  department_id BIGINT NOT NULL,
  snapshot_date DATE NOT NULL,
  warehouse_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  stock_qty DECIMAL(18,4) NOT NULL DEFAULT 0,
  aging_days INT NOT NULL,
  import_batch_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_aging (department_id,snapshot_date,warehouse_id,product_id,aging_days),
  KEY idx_aging_dept_snapshot (department_id,snapshot_date),
  KEY idx_aging_product_snapshot (product_id,snapshot_date)
);

CREATE TABLE IF NOT EXISTS filter_presets (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_pk BIGINT NOT NULL,
  name VARCHAR(64) NOT NULL,
  shop_filter JSON NULL,
  warehouse_filter JSON NULL,
  product_filter JSON NULL,
  include_name_keywords JSON NULL,
  exclude_name_keywords JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_preset_name (user_pk,name),
  CONSTRAINT fk_preset_user FOREIGN KEY (user_pk) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS product_notes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_pk BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  note TEXT NOT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_product_note (user_pk,product_id)
);

CREATE TABLE IF NOT EXISTS todo_tasks (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  task_no VARCHAR(64) NOT NULL UNIQUE,
  department_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  owner_user_pk BIGINT NOT NULL,
  creator_user_pk BIGINT NOT NULL,
  warehouse_id BIGINT NULL,
  shop_id BIGINT NULL,
  target_qty DECIMAL(18,4) NULL,
  assign_date DATE NOT NULL,
  start_date DATE NOT NULL COMMENT '固定为分配日期次日',
  manager_note TEXT NULL,
  owner_note TEXT NULL COMMENT '只有任务负责人本人可修改',
  status ENUM('running','pending_delete','done','delete_rejected') NOT NULL DEFAULT 'running',
  delete_requester_user_pk BIGINT NULL,
  delete_reason TEXT NULL,
  delete_requested_at DATETIME NULL,
  delete_approver_user_pk BIGINT NULL,
  delete_decided_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_todo_owner_status (owner_user_pk,status),
  KEY idx_todo_dept_status (department_id,status)
);

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

CREATE TABLE IF NOT EXISTS task_no_sequences (
  assign_date DATE PRIMARY KEY,
  last_seq INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS expiry_rules (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  scope_type ENUM('global','department','product') NOT NULL,
  department_id BIGINT NULL,
  product_id BIGINT NULL,
  near_days INT NOT NULL DEFAULT 30,
  near_pct DECIMAL(8,4) NOT NULL DEFAULT 10,
  warn_days INT NOT NULL DEFAULT 90,
  warn_pct DECIMAL(8,4) NOT NULL DEFAULT 25,
  updated_by BIGINT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  scope_key VARCHAR(128) GENERATED ALWAYS AS (CONCAT(scope_type,':',IFNULL(department_id,0),':',IFNULL(product_id,0))) STORED,
  UNIQUE KEY uk_expiry_scope (scope_type,department_id,product_id),
  UNIQUE KEY uk_expiry_scope_key (scope_key)
);

CREATE TABLE IF NOT EXISTS import_batches (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  batch_no VARCHAR(64) NOT NULL UNIQUE,
  department_id BIGINT NOT NULL,
  data_type ENUM('sales','inventory','product','aging') NOT NULL,
  business_date DATE NULL,
  original_filename VARCHAR(255) NOT NULL,
  file_sha256 CHAR(64) NOT NULL,
  imported_by BIGINT NOT NULL,
  total_rows INT NOT NULL DEFAULT 0,
  success_rows INT NOT NULL DEFAULT 0,
  error_rows INT NOT NULL DEFAULT 0,
  warning_rows INT NOT NULL DEFAULT 0,
  status ENUM('preview','success','failed','rolled_back') NOT NULL DEFAULT 'preview',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  rolled_back_at DATETIME NULL,
  KEY idx_import_hash_scope (department_id,data_type,business_date,file_sha256),
  KEY idx_import_batches_dept_created (department_id,created_at)
);


CREATE TABLE IF NOT EXISTS import_changes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  import_batch_id BIGINT NOT NULL,
  table_name VARCHAR(64) NOT NULL,
  row_pk BIGINT NOT NULL,
  action ENUM('inserted','updated','deleted') NOT NULL,
  before_data JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_import_changes_batch (import_batch_id,id),
  CONSTRAINT fk_import_change_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(id)
);

CREATE TABLE IF NOT EXISTS import_errors (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  import_batch_id BIGINT NOT NULL,
  row_no INT NULL,
  severity ENUM('error','warning') NOT NULL DEFAULT 'error',
  error_code VARCHAR(64) NOT NULL,
  error_message VARCHAR(1000) NOT NULL,
  raw_data JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_import_errors_batch_severity (import_batch_id,severity,id)
);

CREATE TABLE IF NOT EXISTS login_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_pk BIGINT NULL,
  login_key VARCHAR(128) NOT NULL COMMENT 'user_id或username',
  login_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ip_address VARCHAR(64) NULL,
  user_agent VARCHAR(1000) NULL,
  result ENUM('success','failed') NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_logs (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_pk BIGINT NOT NULL,
  department_id BIGINT NULL,
  action_type VARCHAR(64) NOT NULL,
  action_detail JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_activity_user_time (user_pk,created_at),
  KEY idx_activity_dept_time (department_id,created_at),
  KEY idx_activity_action_time (action_type,created_at)
);

INSERT IGNORE INTO departments(code,name) VALUES ('B2C','B2C事业部');


-- Release-chain migration baseline. Checksums are refreshed by scripts/release_tool.py when migrations run.
INSERT IGNORE INTO schema_migrations(migration_id,app_version,checksum,applied_by) VALUES
('0141_import_pipeline','14.1.0',REPEAT('0',64),'schema'),
('0142_dashboard_indexes','14.2.0',REPEAT('0',64),'schema'),
('0145_import_center_indexes','14.5.0',REPEAT('0',64),'schema'),
('0146_auth_sessions','14.6.0',REPEAT('0',64),'schema'),
('0147_audit_indexes','14.7.0',REPEAT('0',64),'schema'),
('0151_release_chain','15.1.0',REPEAT('0',64),'schema'),
('0152_product_alias_latest_snapshot','15.2.0',REPEAT('0',64),'schema');
