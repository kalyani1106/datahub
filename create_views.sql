-- View 1: Customer Order Summary (joins customers and orders)
CREATE OR REPLACE VIEW customer_order_summary AS
SELECT 
    c.customer_id, 
    c.first_name || ' ' || c.last_name AS customer_name, 
    c.email,
    COUNT(o.order_id) AS total_orders, 
    COALESCE(SUM(o.total_amount), 0.00) AS total_spent
FROM customers c
LEFT JOIN orders o ON c.customer_id = o.customer_id
GROUP BY c.customer_id, c.first_name, c.last_name, c.email;

-- View 2: Order Item Details (joins orders, order_items, and products)
CREATE OR REPLACE VIEW order_item_details AS
SELECT 
    o.order_id,
    o.order_date,
    o.status AS order_status,
    p.product_id,
    p.product_name,
    p.category,
    oi.quantity,
    oi.unit_price,
    (oi.quantity * oi.unit_price) AS line_total
FROM orders o
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id;
