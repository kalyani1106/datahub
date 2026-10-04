-- Query 3: City-wise Sales Distribution
-- Purpose: Calculate customer reach, total orders placed, and revenue generated across cities.
SELECT
    c.city,
    COUNT(DISTINCT c.customer_id) AS number_of_customers,
    COUNT(o.order_id) AS total_orders,
    COALESCE(SUM(o.order_amount), 0.00) AS total_sales
FROM {{ ref('customers') }} c
LEFT JOIN {{ ref('orders') }} o ON c.customer_id = o.customer_id
GROUP BY c.city
ORDER BY total_sales DESC;
