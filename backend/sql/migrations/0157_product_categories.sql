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

-- 将旧的单字段分类回填为可多选的分类关系。商品资料重新导入后会以模板为准全量同步。
INSERT IGNORE INTO product_categories(category_name)
SELECT DISTINCT TRIM(j.category_name)
FROM products p
JOIN JSON_TABLE(
    CONCAT(
        '[',
        REPLACE(JSON_QUOTE(REPLACE(COALESCE(p.category, ''), '，', ',')), ',', '","'),
        ']'
    ),
    '$[*]' COLUMNS(category_name VARCHAR(100) PATH '$')
) j
WHERE TRIM(j.category_name) <> '';

INSERT IGNORE INTO product_category_relations(product_id, category_id)
SELECT p.id, pc.id
FROM products p
JOIN JSON_TABLE(
    CONCAT(
        '[',
        REPLACE(JSON_QUOTE(REPLACE(COALESCE(p.category, ''), '，', ',')), ',', '","'),
        ']'
    ),
    '$[*]' COLUMNS(category_name VARCHAR(100) PATH '$')
) j
JOIN product_categories pc ON pc.category_name=TRIM(j.category_name)
WHERE TRIM(j.category_name) <> '';
