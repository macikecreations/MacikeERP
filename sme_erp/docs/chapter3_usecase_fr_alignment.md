# Chapter 3 Use Case and Functional Requirements Alignment

This document maps the implemented system to Chapter 3 functional requirements and the UML use-case intent.

## Use-Case Actors (Implemented)

- **Administrator**: manages users (via Django admin), products, categories, suppliers, restock, reports, backup.
- **Manager**: manages products, categories, suppliers, restock, reports, backup.
- **Cashier**: performs POS checkout and prints receipt.
- **Auditor**: views reports/receipts/dashboard and exports backup (read-focused role).

## Functional Requirements Traceability

| FR ID | Requirement (Chapter 3) | Current Status | Implementation Notes |
|---|---|---|---|
| FR01 | User management and roles | Partial | User creation/role assignment in Django admin. Dedicated in-app user page pending. |
| FR02 | Secure authentication | Implemented | Login/logout with Django auth and protected views. |
| FR03 | Product management | Implemented | Product create/list with category and supplier references. |
| FR04 | Stock management | Implemented | Restock workflow creates FIFO batches and audit logs. |
| FR05 | POS | Implemented | POS sale form with stock validation and atomic sale flow. |
| FR06 | Invoice generation | Implemented | Receipt page and downloadable PDF invoice. |
| FR07 | Inventory deduction | Implemented | FIFO deduction in transactional stock service. |
| FR08 | Low stock alerts | Implemented | Dashboard low-stock counter and item list. |
| FR09 | Sales reporting | Implemented | Daily/weekly/monthly totals and invoice list. |
| FR10 | Audit trail | Implemented | `StockAuditLog` captures stock-changing actions. |
| FR11 | Dashboard analytics | Partial | KPI cards available; chart visualizations pending. |
| FR12 | Data backup utility | Implemented | CSV export endpoint for backup. |
| FR13 | Profile management | Partial | Profile page with activity visibility; password change UI pending. |
| FR14 | Customer tracking (optional) | Partial | Customer name is captured on invoice; dedicated customer master/credit tracking pending. |

## UML Use-Case Conformance Summary

- The current codebase follows the core use-case flow for:
  - login/authentication
  - create/update inventory data
  - process sale
  - generate receipt
  - view reports
  - enforce role-restricted actions
- Remaining UML-strengthening work:
  - in-app user-management UI (non-admin)
  - password/profile edit screens
  - customer ledger/credit tracking entity
  - graphical analytics panel

## Notes for Chapter 3 Write-up

- Mark implemented requirements as completed in prototype validation.
- Mark partial requirements with "Phase 2 completion" targets.
- If presenting in viva/report defense, use this table as direct evidence mapping between design and implementation.
