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

ALTER TABLE activity_logs ADD INDEX idx_activity_department_time (department_id,created_at);
ALTER TABLE login_logs ADD INDEX idx_login_user_time (user_pk,login_time);


-- 修复 MySQL UNIQUE + NULL 不会阻止重复部门规则的问题。
DELETE er_old FROM expiry_rules er_old
JOIN expiry_rules er_new
  ON er_old.id < er_new.id
 AND er_old.scope_type=er_new.scope_type
 AND IFNULL(er_old.department_id,0)=IFNULL(er_new.department_id,0)
 AND IFNULL(er_old.product_id,0)=IFNULL(er_new.product_id,0);

ALTER TABLE expiry_rules
  ADD COLUMN scope_key VARCHAR(128) GENERATED ALWAYS AS (CONCAT(scope_type,':',IFNULL(department_id,0),':',IFNULL(product_id,0))) STORED,
  ADD UNIQUE KEY uk_expiry_scope_key (scope_key);
