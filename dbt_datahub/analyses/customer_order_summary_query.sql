-- Query 1: Customer Order Summary
-- Purpose: Aggregate customer purchasing activity including order count, cumulative spend, and average order value.
SELECT
    c.customer_id,
    c.customer_name,
    c.city,
    COUNT(o.order_id) AS total_orders,
    COALESCE(SUM(o.order_amount), 0.00) AS total_amount,
    COALESCE(ROUND(AVG(o.order_amount), 2), 0.00) AS average_order_amount
FROM {{ ref('customers') }} c
JOIN {{ ref('orders') }} o ON c.customer_id = o.customer_id
GROUP BY c.customer_id, c.customer_name, c.city
ORDER BY total_amount DESC;
