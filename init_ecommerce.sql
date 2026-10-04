-- 1. Create tables with primary and foreign key constraints

CREATE TABLE IF NOT EXISTS customers (
    customer_id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    city VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    stock_quantity INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED',
    total_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES products(product_id) ON DELETE RESTRICT,
    quantity INT NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    payment_method VARCHAR(30) NOT NULL,
    payment_status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED',
    amount NUMERIC(10, 2) NOT NULL,
    payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Insert sample data

INSERT INTO customers (first_name, last_name, email, city) VALUES
('Aarav', 'Sharma', 'aarav.sharma@example.com', 'Bengaluru'),
('Priya', 'Patel', 'priya.patel@example.com', 'Mumbai'),
('Rohan', 'Verma', 'rohan.verma@example.com', 'Delhi'),
('Ananya', 'Iyer', 'ananya.iyer@example.com', 'Chennai'),
('Vikram', 'Singh', 'vikram.singh@example.com', 'Hyderabad');

INSERT INTO products (product_name, category, price, stock_quantity) VALUES
('Wireless Noise-Canceling Headphones', 'Electronics', 149.99, 50),
('Ergonomic Mechanical Keyboard', 'Electronics', 89.50, 75),
('Ultra-Wide Curved Gaming Monitor', 'Electronics', 399.00, 20),
('Stainless Steel Insulated Water Bottle', 'Home & Kitchen', 24.99, 120),
('Organic Fair-Trade Coffee Beans 1kg', 'Groceries', 29.99, 200);

INSERT INTO orders (customer_id, order_date, status, total_amount) VALUES
(1, '2026-09-20 10:15:00', 'COMPLETED', 239.49),
(2, '2026-09-21 14:30:00', 'COMPLETED', 399.00),
(1, '2026-09-22 09:00:00', 'COMPLETED', 54.98),
(3, '2026-09-23 16:45:00', 'COMPLETED', 174.98),
(4, '2026-09-24 11:20:00', 'COMPLETED', 119.49);

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
(1, 1, 1, 149.99),
(1, 2, 1, 89.50),
(2, 3, 1, 399.00),
(3, 4, 1, 24.99),
(3, 5, 1, 29.99),
(4, 1, 1, 149.99),
(4, 4, 1, 24.99),
(5, 2, 1, 89.50),
(5, 5, 1, 29.99);

INSERT INTO payments (order_id, payment_method, payment_status, amount, payment_date) VALUES
(1, 'CREDIT_CARD', 'COMPLETED', 239.49, '2026-09-20 10:16:00'),
(2, 'UPI', 'COMPLETED', 399.00, '2026-09-21 14:31:00'),
(3, 'DEBIT_CARD', 'COMPLETED', 54.98, '2026-09-22 09:02:00'),
(4, 'CREDIT_CARD', 'COMPLETED', 174.98, '2026-09-23 16:46:00'),
(5, 'NET_BANKING', 'COMPLETED', 119.49, '2026-09-24 11:22:00');
