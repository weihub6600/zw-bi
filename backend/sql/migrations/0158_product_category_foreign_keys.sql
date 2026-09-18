-- Enforce the same relation integrity declared by schema_tables.sql on
-- databases that were upgraded through 0157_product_categories.sql.
-- If historical orphan rows exist, this migration intentionally fails instead
-- of deleting or guessing at business data; clean those rows in a reviewed
-- data-fix operation before retrying the release.

SET @add_product_category_product_fk = IF(
    EXISTS(
        SELECT 1
        FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=DATABASE()
          AND CONSTRAINT_NAME='fk_product_category_product'
    ),
    'SELECT 1',
    'ALTER TABLE product_category_relations ADD CONSTRAINT fk_product_category_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE'
);
PREPARE stmt_product_category_product_fk FROM @add_product_category_product_fk;
EXECUTE stmt_product_category_product_fk;
DEALLOCATE PREPARE stmt_product_category_product_fk;

SET @add_product_category_category_fk = IF(
    EXISTS(
        SELECT 1
        FROM information_schema.REFERENTIAL_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA=DATABASE()
          AND CONSTRAINT_NAME='fk_product_category_category'
    ),
    'SELECT 1',
    'ALTER TABLE product_category_relations ADD CONSTRAINT fk_product_category_category FOREIGN KEY (category_id) REFERENCES product_categories(id) ON DELETE CASCADE'
);
PREPARE stmt_product_category_category_fk FROM @add_product_category_category_fk;
EXECUTE stmt_product_category_category_fk;
DEALLOCATE PREPARE stmt_product_category_category_fk;
