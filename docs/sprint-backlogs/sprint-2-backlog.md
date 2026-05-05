# Sprint 2 Backlog
**Duration:** Weeks 7-10 of Term 2  
**Status:** Completed  
**Goals:** Expand on basic functionalities developed in Sprint 1, integrate all developed features together, complete basic order processing, and address high priority test cases.

### Sprint 2 Highlevel Objectives
1. Assign development tasks in the Product Backlog (Kanban) based on the high priority (and remaining critical) test cases.
2. Expand on developed Producer functionalities (surplus discounts, seasonal availability, settlements..)
3. Expand on developed Customer functionalities (order placement for multi-vendor and single-vendor orders, order history..)
4. Integrate developed components with eachother to show a clear process flow of:
    - producer creates account → logs in → adds a product listing
    - customer creates account → logs in → views that product's listing → adds it to their basket → views order summary and clicks checkout
    - payment is processed through external mock → success message with recepit is returned and order is placed.
5. Add a user profile page with the options to view and update user account details.

## Sprint 2 Tasks Breakdown

## Week 1: Independent Development

#### Assigned To: Matt Wood
- [x] Create a user profile's view page with functionality to:
    - modify email, phone number, full name, delivery address, and postcode.
    - change password.
    - delete user account.

#### Assigned to: Amine Ziani
- [x] finish integration between customer checkout button and external payment processing
    - add fields for delivery address, delivery type, and payment receipt review before proceeding with payment

#### Assigned To: Dina Metwalli
- [x] Complete single-vendor and multi-vendor order placement
    - [x] when a customer checks out with items from different producers in their baskets, the order model should keep clear records of the producer, creating separate orders for each with the correct payment assigned.
    - [x] if multiple items are under a single producer, they should all be placed in the same order.
    - [x] if the basket contains items only from one producer, it should be placed under one order for both customer and producer.

#### Assigned To: Leon Stansfield
- [x] Develop an order view for producers
    - [x] producers should see a highlevel view of incoming orders including a timestamp of when they were placed.
    - [x] producers should be able to click on each order to view its details, including order number, the products, each product's amount, order subtotal, and the customer contact details.

#### Assigned To: Kaan Karadag
- [x] Notifications integration for order placement
    - [x] implement functionality to notify producers of an incoming order
    - [x] customers should get a notification on every order status update when a producer updates it, including pending, confirmed, ready (for delivery or collection), delivered or completed, and cancelled.

## Week 2: Any Remaining Functionalities

#### Assigned To: Matt Wood
- [x] Work on payment processing to be integrated with external mock and placed orders
- [x] Add discount management for payments including bulk order discounts and surplus discounts.
    - This should be reflected on the items and inside the customer's basket when items are added to it, showing the discount that will be applied and the order summary's subtotal with the added discount.
- [x] Add a 404 error page for page not found errors.

#### Assigned to: Amine Ziani
- [x] Add payment fallback handling and processing in case of failure. This includes:
    - [x] transaction retries in case of failed transactions (not enough balance, API failure...)
    - [x] refunds in case of order cancellation by customer.

#### Assigned To: Dina Metwalli
- [x] Complete/continue single-vendor and multi-vendor order placement
    - [x] in either case of single or multi-vendor orders, each order should be linked back to an overall order receipt for the customer to view what they ordered regardless of its producer.
    - [x] each order should also link back to the items its associated with depending on the producer.
- [x] Start developing order history view for customers
- [-] Add functionality for customers to reorder the same orders from their history

#### Assigned To: Leon Stansfield
- [x] Continue developing order view for producers
    - [x] validate a 48-hour lead time to ensure producers have enough time to prepare.
    - [-] add functionality for producers to view the order delivery type

#### Assigned To: Kaan Karadag
- [x] Notifications integration for order placement
    - [x] implement functionality to notify producers of an incoming order
    - [x] customers should get a notification on every order status update when a producer updates it, including pending, confirmed, ready (for delivery or collection), and delivered or completed.

## Week 3: Integration

#### Assigned To: All Members
- [x] cleanup any failed or incomplete functionalities assigned to you and test on related test cases to ensure success.
- [x] add any remaining error handling cases for user authorization and process failures.

#### Assigned To: Matt Wood
- [x] Integrate developed payment processing with discounts to the basket view and external mock
    - [x] modify the data fields currently sent to the external payment system as needed.
- [x] Add the UI elements needed to show the integrated discounts processing.
- [x] Add user accessibility features such as an accessibile mode for the UI to support colour-blind users.

#### Assigned to: Amine Ziani
- [x] Implement the frontend web templates to show payment status:
    - this includes success, failure, refund, etc.

#### Assigned To: Leon Stansfield
- [x] implement the needed UI template with the correct styling to sort orders by date of placement.
- [x] Add functionality for producers to modify the order status (initially set to pending, then they can update to confirmed, ready for collection, or delivered).

#### Assigned To: Kaan Karadag
- [x] Dispatch notifications when an order status is updated by a producer user.

## Sprint 2 Deliverables

### 1. Multi-vendor and single-vendor order split
Orders are split and recorded in the DB accordingly depending on if the order items are from a single producer or multiple.

### 2. Producer Advanced Order View
Producers should now be able to view incoming orders, update order status, and see each orders details along with its customer's contact information.

### 3. Notifications & Updates
Customers should get notifications of their order status and changes made to it by Producers. They should also have availability to cancel orders and producers be notified of that.

### 4. Payment Integration
Payment integration through Stripe when a customer clicks on Checkout, with the ability to cancel and refund when needed.

### 5. Discounts
The application of discounts on producer items and their calculation in order summary subtotal in the customer's basket.