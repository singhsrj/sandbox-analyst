# Revenue Drop Analysis – March 2025

**Summary**
- Total revenue for **February 2025**: **$506,271.04**
- Total revenue for **March 2025**: **$441,892.21**
- **Drop:** **$64,378.83** (**‑12.72%**) compared to the prior month.

**Key Findings**
- The overall decline is driven primarily by a sharp fall in the **South** region, which lost **$127,707** (**‑82.66%**) month‑over‑month.
- Other regions showed growth:
  - **North:** +$33,318 (**+31.24%**)
  - **West:** +$17,532 (**+16.42%**)
  - **East:** +$17,950 (**+22.02%**)
- **Central** region experienced a modest decline of **$5,471** (**‑9.63%**).

**Chart**
- Bar chart comparing February and March 2025 revenue by region: `region_revenue_feb_mar.png`.

**SQL Queries Used**
```sql
-- Monthly revenue (delivered orders only)
SELECT DATE_TRUNC('month', order_date) AS month,
       SUM(total_amount) AS revenue
FROM analytics.orders
WHERE status = 'delivered'
  AND order_date >= '2024-01-01' AND order_date < '2025-05-01'
GROUP BY month
ORDER BY month;
```
```sql
-- Revenue by region for March 2025
SELECT r.region_name,
       SUM(o.total_amount) AS revenue
FROM analytics.orders o
JOIN analytics.regions r ON o.region_id = r.region_id
WHERE o.status = 'delivered'
  AND o.order_date >= '2025-03-01' AND o.order_date < '2025-04-01'
GROUP BY r.region_name
ORDER BY revenue DESC;
```
```sql
-- Revenue by region for February 2025
SELECT r.region_name,
       SUM(o.total_amount) AS revenue
FROM analytics.orders o
JOIN analytics.regions r ON o.region_id = r.region_id
WHERE o.status = 'delivered'
  AND o.order_date >= '2025-02-01' AND o.order_date < '2025-03-01'
GROUP BY r.region_name
ORDER BY revenue DESC;
```

**Assumptions & Caveats**
- Revenue is defined as the sum of `orders.total_amount` for orders with `status = 'delivered'`. Cancelled orders are excluded.
- The analysis uses the data available up to **April 1 2025**; any orders after that date are not included.
- Region names are taken from the `regions` table; the dataset contains only five regions.
- Data quality checks revealed no duplicate order IDs or missing `total_amount` values for the queried period.
