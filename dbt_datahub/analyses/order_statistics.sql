-- Query 4: Order Statistics and Key Performance Indicators
-- Purpose: Compute key performance metrics: total orders, total revenue, average order value, and highest order value.
SELECT
    COUNT(order_id) AS total_orders,
    COALESCE(SUM(order_amount), 0.00) AS total_revenue,
    COALESCE(ROUND(AVG(order_amount), 2), 0.00) AS average_order_value,
    COALESCE(MAX(order_amount), 0.00) AS max_order_value
FROM {{ ref('orders') }};
