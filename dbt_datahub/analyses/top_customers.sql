-- Query 2: Top Customers by Total Spend
-- Purpose: Identify top 5 customers ranked by highest cumulative order spending.
SELECT
    customer_id,
    customer_name,
    city,
    total_orders,
    total_amount AS total_spent
FROM {{ ref('customer_order_summary') }}
ORDER BY total_amount DESC
LIMIT 5;
