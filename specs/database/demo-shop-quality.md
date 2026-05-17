# Database Quality Checks: Demo Shop

Runnable SELECT-only checks for the Quorvex Demo Shop schema.

```sql
-- check: customers_email_present | null_check | critical
SELECT id, full_name
FROM quorvex_demo.customers
WHERE email IS NULL
LIMIT 100
```

```sql
-- check: customers_email_format | pattern | high
SELECT id, email, full_name
FROM quorvex_demo.customers
WHERE email !~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$'
LIMIT 100
```

```sql
-- check: customers_unique_email | uniqueness | high
SELECT email, COUNT(*) AS duplicate_count
FROM quorvex_demo.customers
GROUP BY email
HAVING COUNT(*) > 1
LIMIT 100
```

```sql
-- check: order_items_quantity_positive | range | critical
SELECT id, order_id, product_id, quantity
FROM quorvex_demo.order_items
WHERE quantity <= 0
LIMIT 100
```

```sql
-- check: payments_match_order_total | custom | medium
SELECT o.id AS order_id, o.total_amount AS order_total, COALESCE(SUM(p.amount), 0) AS paid_total
FROM quorvex_demo.orders o
LEFT JOIN quorvex_demo.payments p ON p.order_id = o.id
WHERE o.status IN ('paid', 'shipped')
GROUP BY o.id, o.total_amount
HAVING COALESCE(SUM(p.amount), 0) <> o.total_amount
LIMIT 100
```
