\echo '=== Query 1: Filtered JOIN (Customers & Orders > $100) ==='
SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer_name, o.order_id, o.order_date, o.total_amount
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
WHERE o.total_amount > 100.00
ORDER BY o.total_amount DESC;

\echo '=== Query 2: Aggregate & GROUP BY (Total Spend per Customer) ==='
SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer_name, COUNT(o.order_id) AS total_orders, SUM(o.total_amount) AS total_spent
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
GROUP BY c.customer_id, c.first_name, c.last_name
ORDER BY total_spent DESC;

\echo '=== Query 3: Multi-Table Relationship (Customer -> Orders -> Order_Items -> Products) ==='
SELECT o.order_id, c.first_name || ' ' || c.last_name AS customer, p.product_name, oi.quantity, oi.unit_price, (oi.quantity * oi.unit_price) AS line_total
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
ORDER BY o.order_id, p.product_name;

\echo '=== Query 4: Payment Reconciliation (Orders -> Payments) ==='
SELECT o.order_id, o.total_amount AS order_total, pay.payment_method, pay.amount AS payment_amount, pay.payment_status
FROM orders o
JOIN payments pay ON o.order_id = pay.order_id
ORDER BY o.order_id;
