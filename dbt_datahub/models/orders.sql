SELECT
    order_id,
    customer_id,
    product_id,
    quantity,
    order_amount,
    order_date
FROM {{ source('public_source', 'raw_orders') }}
