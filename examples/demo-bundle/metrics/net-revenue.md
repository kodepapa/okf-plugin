---
type: Metric
title: Net Revenue
description: Recognized revenue after refunds and discounts.
tags: [finance, revenue]
timestamp: 2026-07-14T00:00:00Z
---

Net revenue is calculated from [Orders](../tables/orders.md) as gross recognized revenue minus refunds and discounts.

# Definition

`SUM(gross_revenue - refund_amount - discount_amount)`
