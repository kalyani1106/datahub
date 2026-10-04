SELECT
    customer_id,
    customer_name,
    email,
    city
FROM {{ source('public_source', 'raw_customers') }}