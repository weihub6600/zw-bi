CREATE TABLE IF NOT EXISTS product_categories (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    category_name VARCHAR(100) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_product_category_name(category_name)
);

CREATE TABLE IF NOT EXISTS product_category_relations (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    product_id BIGINT NOT NULL,
    category_id BIGINT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_product_category(product_id, category_id),
    INDEX idx_product_category_product(product_id),
    INDEX idx_product_category_category(category_id)
);