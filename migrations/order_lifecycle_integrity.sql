-- Migration: order lifecycle integrity (review round 3, step 3)
-- Date: 2026-11-06
--
-- 1. CHECK constraints that back up the Python validation. A request that slips
--    past Cart.parse_quantity / Product.parse_price still cannot store a negative
--    cart line, a free product or stock below zero.
-- 2. Stock is now reserved when an order is PLACED (Product.reserve_stock), not
--    when it is paid. Orders created by the old code are still `pending` without
--    their stock taken; cancelling one would put back units that were never
--    removed. Reserve them now, as the new code would have done.
--    (Digital products keep no stock and are skipped.)
--
-- Run as the postgres superuser, then re-check the result before COMMIT is
-- reached: any row violating a constraint aborts the whole migration.

BEGIN;

UPDATE products p
SET quantity = GREATEST(0, p.quantity - o.reserved)
FROM (
    SELECT product_id, SUM(quantity) AS reserved
    FROM orders
    WHERE status = 'pending'
    GROUP BY product_id
) o
WHERE p.id = o.product_id
  AND NOT p.is_digital;

ALTER TABLE products
    -- Upper bound included on purpose: PostgreSQL sorts NaN above every number,
    -- so CHECK (price > 0) alone accepts NaN. (price <= 100000) does not.
    ADD CONSTRAINT ck_product_price_positive CHECK (price > 0 AND price <= 100000),
    ADD CONSTRAINT ck_product_quantity_nonnegative CHECK (quantity >= 0);

ALTER TABLE cart_items
    ADD CONSTRAINT ck_cart_item_quantity_positive CHECK (quantity > 0);

ALTER TABLE orders
    ADD CONSTRAINT ck_order_quantity_positive CHECK (quantity > 0),
    ADD CONSTRAINT ck_order_total_nonnegative CHECK (total_price >= 0);

COMMIT;
