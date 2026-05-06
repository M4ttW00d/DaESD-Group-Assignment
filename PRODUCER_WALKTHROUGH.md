# Producer Service & Dashboard: Technical Walkthrough

This document provides a technical overview of how the Producer features are implemented in the Bristol Regional Food Network platform.

---

## 1. Producer Accounts & Profiles
**Key Files:** `services/platform-service/users/models.py`

*   **Role-Based Access:** Users have a `role` field (ADMIN, PRODUCER, CUSTOMER). 
*   **ProducerProfile:** When a user is a Producer, they have a linked `ProducerProfile` containing:
    *   `business_name`, `business_address`.
    *   `postcode` (Critical for **Food Miles** calculations).
    *   `bio` (Used for "Farm Stories").

---

## 2. Making & Managing Products
**Key Files:** `services/platform-service/products/models.py`, `views.py`

Producers manage their inventory via the `Product` model.

### Key Product Features:
*   **Categorization:** Products are linked to a `Category` (Vegetables, Dairy, etc.).
*   **Inventory Tracking:** `stock_quantity` tracks real-time inventory.
*   **Low Stock Alerts:** `low_stock_threshold` triggers notifications when items run low.
*   **Seasonality:** `seasonal_start_month` and `seasonal_end_month` automate visibility. Products outside this range are marked "Out of Season" on the frontend.
*   **Health & Safety:** Includes `allergens` (JSON list of the UK 14) and `allergen_info` text.
*   **Pricing:** `price` and `unit` (e.g., £ per kg).

---

## 3. Producer Dashboard (Ordering & Workflow)
**Key Files:** `services/platform-service/orders/models.py`, `views.py`

The "Dashboard" is conceptually the collection of views allowing producers to manage their business.

### Viewing Orders:
*   **Order Splitting:** When a customer checks out, the system creates a `CustomerOrder` (the whole basket) and splits it into individual `Order` objects—one for each producer.
*   **Producer Filtering:** The `OrderListView` automatically filters so producers only see orders containing *their* products.

### Updating Status:
Producers transition orders through a defined lifecycle using `OrderStatusUpdateView`:
1.  **PENDING:** Newly placed order.
2.  **CONFIRMED:** Producer has accepted the order.
3.  **READY:** Items are packed and ready for collection/delivery.
4.  **DELIVERED:** Order completed.

*   Every status change is logged in the `OrderStatusLog` for transparency.
*   **Notifications:** Status changes trigger calls to the `notifications-service` to alert the customer.

---

## 4. Reviews & Seller Responses
**Key Files:** `services/platform-service/reviews/models.py`, `views.py`

*   **Feedback Loop:** Customers leave a `Review` (1-5 stars + comment) linked to a specific `Product` and `Order`.
*   **Seller Response:** Producers can use the `seller_response` field to reply to feedback directly, fostering community trust.
*   **Verified Purchase:** Reviews are linked to `Order` IDs to prove the customer actually bought the item.

---

## 5. Farm Stories & Engagement
**Key Files:** `services/platform-service/products/models.py` (Models: `FarmStory`, `Recipe`)

Producers engage customers through "Educational Content":
*   **Farm Stories:** Blog-style posts (`title`, `content`, `image`) to share the "Farm to Fork" journey.
*   **Recipes:** Producers can share instructions and ingredients for their products, tagged by season.

---

## Summary of Workflow for Presentation
1.  **Onboarding:** Producer creates account -> Fills Profile (Postcode is vital).
2.  **Inventory:** Producer adds Products (Sets stock, allergens, and seasonal dates).
3.  **Sales:** Customer buys -> Order is split -> Producer sees their specific sub-order.
4.  **Fulfillment:** Producer updates status (Pending -> ... -> Delivered) -> Customer notified.
5.  **Retention:** Customer reviews -> Producer responds -> Producer shares a "Farm Story" to keep engagement high.
