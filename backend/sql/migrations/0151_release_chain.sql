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
