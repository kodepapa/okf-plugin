---
type: BigQuery Table
title: Orders
description: One row per completed customer order.
tags: [sales, orders]
timestamp: 2026-07-14T00:00:00Z
---

The canonical order fact used by [Net Revenue](../metrics/net-revenue.md).

# Schema

| Column | Type | Description |
|---|---|---|
| `order_id` | STRING | Globally unique order identifier. |
| `gross_revenue` | NUMERIC | Recognized gross revenue. |
| `refund_amount` | NUMERIC | Refunded amount. |
| `discount_amount` | NUMERIC | Discount amount. |
