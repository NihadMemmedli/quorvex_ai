# Database Quality Checks: ai-generated-quorvex-demo-shop-20260517-1015

## Check 1: customers_no_null_email
**Description**: Verify all customers have a non-null email address
**Type**: null_check
**Severity**: critical
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT id, full_name, status, created_at FROM customers WHERE email IS NULL LIMIT 100
```

## Check 2: customers_no_null_full_name
**Description**: Verify all customers have a non-null full_name
**Type**: null_check
**Severity**: high
**Table**: customers
**Column**: full_name
**Expect Empty**: True

```sql
SELECT id, email, status, created_at FROM customers WHERE full_name IS NULL LIMIT 100
```

## Check 3: customers_no_null_status
**Description**: Verify all customers have a non-null status
**Type**: null_check
**Severity**: high
**Table**: customers
**Column**: status
**Expect Empty**: True

```sql
SELECT id, email, full_name, created_at FROM customers WHERE status IS NULL LIMIT 100
```

## Check 4: customers_no_null_created_at
**Description**: Verify all customers have a non-null created_at timestamp
**Type**: null_check
**Severity**: medium
**Table**: customers
**Column**: created_at
**Expect Empty**: True

```sql
SELECT id, email, full_name, status FROM customers WHERE created_at IS NULL LIMIT 100
```

## Check 5: customers_unique_email
**Description**: Detect duplicate emails in customers table - email must be unique per customer
**Type**: uniqueness
**Severity**: critical
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT email, COUNT(*) AS occurrences FROM customers WHERE email IS NOT NULL GROUP BY email HAVING COUNT(*) > 1 LIMIT 100
```

## Check 6: customers_unique_id
**Description**: Verify primary key uniqueness on customers.id
**Type**: uniqueness
**Severity**: critical
**Table**: customers
**Column**: id
**Expect Empty**: True

```sql
SELECT id, COUNT(*) AS occurrences FROM customers GROUP BY id HAVING COUNT(*) > 1 LIMIT 100
```

## Check 7: customers_unique_email_case_insensitive
**Description**: Detect duplicate emails with case-insensitive comparison (e.g. User@x.com vs user@x.com)
**Type**: uniqueness
**Severity**: high
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT LOWER(email) AS normalized_email, COUNT(*) AS occurrences FROM customers WHERE email IS NOT NULL GROUP BY LOWER(email) HAVING COUNT(*) > 1 LIMIT 100
```

## Check 8: customers_email_format_valid
**Description**: Validate customer email follows a basic email format (contains @ and a domain)
**Type**: pattern
**Severity**: high
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT id, email, full_name FROM customers WHERE email IS NOT NULL AND email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' LIMIT 100
```

## Check 9: customers_email_no_whitespace
**Description**: Detect emails containing leading/trailing/internal whitespace
**Type**: pattern
**Severity**: medium
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT id, email FROM customers WHERE email IS NOT NULL AND (email ~ '\s' OR email <> TRIM(email)) LIMIT 100
```

## Check 10: customers_email_lowercase
**Description**: Detect emails not stored in lowercase (best practice for normalization)
**Type**: pattern
**Severity**: low
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT id, email FROM customers WHERE email IS NOT NULL AND email <> LOWER(email) LIMIT 100
```

## Check 11: customers_status_allowed_values
**Description**: Verify customer status values fall within expected enum-like set
**Type**: range
**Severity**: high
**Table**: customers
**Column**: status
**Expect Empty**: True

```sql
SELECT id, email, status FROM customers WHERE status NOT IN ('active','inactive','suspended','pending','deleted') LIMIT 100
```

## Check 12: customers_status_case_consistency
**Description**: Detect inconsistent casing in status values (e.g. 'Active' vs 'active')
**Type**: pattern
**Severity**: medium
**Table**: customers
**Column**: status
**Expect Empty**: True

```sql
SELECT id, status FROM customers WHERE status IS NOT NULL AND status <> LOWER(status) LIMIT 100
```

## Check 13: customers_full_name_not_empty
**Description**: Detect blank or whitespace-only full_name values
**Type**: pattern
**Severity**: high
**Table**: customers
**Column**: full_name
**Expect Empty**: True

```sql
SELECT id, email, full_name FROM customers WHERE full_name IS NOT NULL AND LENGTH(TRIM(full_name)) = 0 LIMIT 100
```

## Check 14: customers_full_name_length_reasonable
**Description**: Detect suspiciously short or excessively long full_name values
**Type**: range
**Severity**: low
**Table**: customers
**Column**: full_name
**Expect Empty**: True

```sql
SELECT id, email, full_name, LENGTH(full_name) AS name_length FROM customers WHERE full_name IS NOT NULL AND (LENGTH(TRIM(full_name)) < 2 OR LENGTH(full_name) > 200) LIMIT 100
```

## Check 15: customers_created_at_not_future
**Description**: Detect customers with a created_at timestamp in the future
**Type**: range
**Severity**: high
**Table**: customers
**Column**: created_at
**Expect Empty**: True

```sql
SELECT id, email, created_at FROM customers WHERE created_at > NOW() LIMIT 100
```

## Check 16: customers_created_at_not_too_old
**Description**: Detect customers with a suspiciously old created_at (before year 2000)
**Type**: range
**Severity**: medium
**Table**: customers
**Column**: created_at
**Expect Empty**: True

```sql
SELECT id, email, created_at FROM customers WHERE created_at < '2000-01-01'::timestamptz LIMIT 100
```

## Check 17: customers_freshness_recent_signup
**Description**: Verify the customers table has recent activity (at least one signup in the last 365 days)
**Type**: freshness
**Severity**: medium
**Table**: customers
**Column**: created_at
**Expect Empty**: True

```sql
SELECT 'stale_customers_table' AS issue, MAX(created_at) AS latest_signup FROM customers HAVING MAX(created_at) < NOW() - INTERVAL '365 days' OR MAX(created_at) IS NULL LIMIT 100
```

## Check 18: customers_no_orphan_orders
**Description**: Detect orders referencing non-existent customers (orphan orders)
**Type**: referential
**Severity**: critical
**Table**: customers
**Column**: id
**Expect Empty**: True

```sql
SELECT o.id AS order_id, o.customer_id, o.created_at FROM orders o LEFT JOIN customers c ON c.id = o.customer_id WHERE c.id IS NULL LIMIT 100
```

## Check 19: customers_no_orphan_support_tickets
**Description**: Detect support_tickets referencing non-existent customers
**Type**: referential
**Severity**: high
**Table**: customers
**Column**: id
**Expect Empty**: True

```sql
SELECT t.id AS ticket_id, t.customer_id, t.subject FROM support_tickets t LEFT JOIN customers c ON c.id = t.customer_id WHERE c.id IS NULL LIMIT 100
```

## Check 20: customers_active_have_valid_email
**Description**: Active customers must have a valid (non-empty, well-formed) email address
**Type**: custom
**Severity**: high
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT id, email, status FROM customers WHERE status = 'active' AND (email IS NULL OR LENGTH(TRIM(email)) = 0 OR email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$') LIMIT 100
```

## Check 21: customers_email_domain_not_local
**Description**: Detect emails using test/local domains (localhost, example.com, test.com) that should not be in production data
**Type**: pattern
**Severity**: medium
**Table**: customers
**Column**: email
**Expect Empty**: True

```sql
SELECT id, email FROM customers WHERE email IS NOT NULL AND (email ILIKE '%@localhost%' OR email ILIKE '%@example.%' OR email ILIKE '%@test.%' OR email ILIKE '%@invalid%') LIMIT 100
```
