ALTER TABLE activity_logs ADD INDEX idx_activity_dept_time (department_id,created_at);
ALTER TABLE activity_logs ADD INDEX idx_activity_action_time (action_type,created_at);
