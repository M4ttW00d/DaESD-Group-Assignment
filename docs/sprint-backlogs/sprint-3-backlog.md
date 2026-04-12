# Sprint 3 Backlog
**Duration:** Weeks 11-13 of Term 2  
**Status:** In Progress  
**Goals:** Finish all remaining low-priority test cases and add extra production qualities to the system that further address non-functional requirements.

### Sprint 3 Highlevel Objectives
1. Assign development tasks in the Product Backlog (Kanban) based on the low priority (and any other remaining) test cases.
2. Complete reordering from customer order history, full notifications system, an external notifications API, and any remaining producer or UI elements.
3. Show the final process flow of the system, with all fully components integrated.
4. Ensure extra production-level qualities such as soft-deletes, data retention in accordance with GDPR and local legislation, and user accessibility features.


## Sprint 3 Tasks Breakdown

## Week 1: Remaining Test Cases

#### Assigned To: Matt Wood
- [x] Add a custom UI popup for confirmation on dangerous/delete actions for a professional look.
- [] Show surplus discounts and calculations during checkout as well (only shown in basket currently).
- [x] Add a site favicon.
- [x] Complete remaining integration for 5% commission discount on orders.
- [] Add the food miles calculation using any external integrations (if needed).
    - [] Show the food miles display on any product details page, calculated in miles based on customer and producer post codes.
    - [] Add functionality to calculate total food miles calculation for an order with products from different vendors.

#### Assigned to: Amine Ziani
- [] Develop the needed business logic for processing weekly payment settlements
    - This includes audit trails for the settlements/transactions.
    - A "Payments" or "Financial Reports" section in the UI should be shown for Producer users only to include this information.
    - The settlements should have a clear breakdown of the values of the total order, the 5% network commission, the producer's cut, both in a highlevel week summary and a break down by each order for that week.

#### Assigned To: Dina Metwalli
- [] Add customer ability to reorder from their order history
    - Customer should be able to click on a certain order and view the items they ordered, with links back to the items under the producer's listing.
    - Clicking Order Again will prompt the user to confirm if they'd like to order these same items again, and proceed to the basket page with the items populated for the customer to modify as needed.
- [] Add special checkout process for community group representative users (by including a special instructions section for producers to view).
    - [] Test bulk orders by community group users still function as expected and system allows bulk ordering.
- [] reinforce 48 hour lead time in UI on checkout.

#### Assigned To: Leon Stansfield
- [] Add functionality for producers to upload farm stories/recipes/educational content with the appropriate type tags.
    - [] Add a link to the related producer's products mentioned in the recipe.
    - [] Add needed UI pages for publishing the farm story/recipe as a producer.
    - [] Add the needed UI page to read the farm story as a customer.

#### Assigned To: Kaan Karadag
- [] Complete the UI page for the notifications service API to show notifications for both producers and customer users on order updates/comments.
- [] Add notifications for LOW STOCK alerts to go to the resepctive item producers.

## Week 2: Full Integration

#### Assigned To: Matt Wood
- [] Add registration for community group representative users (note: should be checked later).
- [] Apply discounts to bulk orders as well, based on the order quantity and to be reflected both in the basket subtotal and the checkout/order summary pages.
- [] Integrate discounts and payment receipts to the customer's order history as needed, as well as the overall order status.

#### Assigned to: Amine Ziani
- [] Ensure bulk orders payment still works with current mock payment gateway integration and payments are split by producer.
- [] Assist team members with other remaining functionalities, including the external emailing/notifications API.

#### Assigned To: Dina Metwalli
- [] Add a warning to show customers on replacing orders from history in case any of the order's items are unavailable as of current time.
    - This should clearly specify which item(s) is currently unavailable.
    - If they customer would still like to proceed, it will take the same process of going to the basket page.
    - Proceeding to checkout should function the same.
- [] Add recurring orders setup for restaurant owner customers.
    - Includes choosing the products by browsing, setting the quantity for each item, confirming weekly recurrence and delivery days, and reviewing the order summary and checkout.

#### Assigned To: Leon Stansfield
- [] Fix and test image loading functionality for adding products.
    - This should be tested across ALL pages where product images appear.
- [] Complete customer reviews by adding a review submission form.
- [] Add seasonal availability filtering in the UI to work with the existing model.

#### Assigned To: Kaan Karadag
- [] Complete an integration with an external email API service to send the same notifications outside of the BRFN website as well.
    - These emails should go to both producers and customers on order updates as needed.
- [] Add notifications to go out to customers when a producer has a limited time offer or discount deal.

## Week 3: Final Cleanup

#### Assigned To: All Members
- [] Test all integrated functionalities on the same system and using multiple users.
    - Ensure all test cases are met.
    - Ensure production-level quality is considered against all functionalities.
    - **Check against functional and non-functional requirements list.**

#### Assigned To: Matt Wood
- [] Integrate the added discounts with the external payment service flow.
- [] Add date filtering for commission monitoring in the admin dashboard.
    - [] Add the financial reports section in the dashboard with report generation and download functionalities.

#### Assigned to: Amine Ziani
- [] Test and fix any edge cases found around order cancellation, refund processing, etc. both in the backend and UI.

#### Assigned To: Leon Stansfield
- [] Add order type to show for producers in each order's details (regular customer order, recurring order, bulk order by community group representative)
- [] Add field in UI for producer order to see special instructions added by community group representative during order placement.

#### Assigned To: Kaan Karadag
- [] Add extra notifications functionalities (e.g. the ability for users to choose email notification preferences, or notifications on farm stories additon, or an emergency recall procedure in case any contaminated products have been delivered to customers).

#### Assigned To: Dina Metwalli
- [] Add soft updates for product availability once a customer places products in their basket and test using two users.
- [] Update actual product availability/stock once customer places order.
- [] Add functionality to temporarily modify established recurring order templates and test that it only updates the next order placed, not the template itself.


## Sprint 3 Deliverables

The final working system with all features integrated and test cases addressed.