# Sprint 1 Backlog
**Duration:** Weeks 4-6 of Term 2  
**Status:** Completed  
**Goals:** Basic functionalities implemented, UI templates developed, and DB Models setup.

## Sprint 1 Highlevel Objectives
1. Assign development tasks in the Product Backlog (Kanban) based on team formation in Sprint 0.
2. Finalise Docker setup & architecture for all services.
3. Implement UI templates to be used across all services and components.
4. Complete core components and database models development to have a working prototype.

## Sprint 1 Tasks Breakdown

### Week 1: Preparation
#### Assigned To: All Members
- [x] Each team member to finish their introduction to Docker and Django

#### Assigned To: Matt Wood
- [x] MySQL database container working: set up the database connection details in the .env file (including Name, Password, Host, etc.) and ensure correct containerisation setup in docker-compose, with the services connected to the DB.
- [x] Database connections verified: verify that the above task was completed and that the database loads as expected in MySQL Workbench.
- [x] Each service has basic Django project initialized: Create a Django Project for each service where the apps, acting as its components, will be initialised inside of.

#### Assigned To: Leon & Dina
- [x] Clean up the documentation from Sprint 0: remove any redundancies
- [x] Define basic functional and non-functional requirements according to the case study
- [x] Review the released test cases and refine requirements to adhere to MoSCoW with respect to the related priority in the test cases.
- [x] Create Kanban board and start adding high priority development tasks related to week 3 inside.

### Week 2: Database Models Implementation, User Profiles, and Core Functionalities

#### Assigned To: Leon Stansfield
- [x] Set up DB schema:
    - create ER diagram to represent the overall DB relations
    - create the basic models for orders, products, reviews, users, and user profiles to allow the rest of the team to start development and focus on business logic
- [x] Set up REST APIs to interact with the implemented DB models accross the services
    - create a minimal frontend to test the API directly
    - setup the serializers, urls, and views for each of the models' apps inside the platform-api service
    - setup login and logout functionalities for the created producer and customer profile models

#### Assigned To: Dina Metwalli
- [x] Develop the core functionalities of the customer basket component:
    - limit the basket view to customers only through user authentication and role verification
    - implement the needed serializers, urls, and basket views
    - add the business logic to add and remove items to the basket, increase or decrease added quantity, clear the basket

#### Assigned To: Matt Wood
- [x] implement the needed templates and frontend service's views to connect the basic API to the frontend
- [x] decide on and implement the CSS styling for the frontend view while prioritising user friendly functionality 
- [x] complete filtering by category, producer, and product search in the UI
- [x] add the needed links for signing in and signing out
- [x] implement the login and registration pages, unique to customer and producer profiles
- [x] implement the product details page, showing an item's description, allergen warnings, category, producer, farm origin...
- [x] add error fields in the UI to accommodate for error handling on failure returns
- [x] link the implemented pages to the database users and products models through the frontend API views

#### Assigned To: Amine Ziani
- [x] Evaluate external payment processing services
    - decide on an external sandbox payment system for integration and agree with the rest of the team (decided on Stripe)

### Week 3: Project Architecture & Core Business Logic
#### Assigned To Dina Metwalli
- [x] revaluate the project structure based on feedback from last week's standup
    - consider inter-service communication and a micro-services architecture where services that can be fully separated (such as the Notifications API) should be standalone and those that are interdependent should be under the platform-api service
    - create a Service Relationships Diagram to show the new project structure
- [x] finish customer basket implementation
    - calculate item subtotal based on units
    - show an order summary at the end with the order subtotal and total number of items
    - link the frontend views to the basket API
    - create a UI template following the same style and base developed by Matt.

#### Assigned To: Matt Wood
- [x] refine frontend CSS styling to be more user-friendly.
- [x] create a frontend guide for other team members to follow when creating their own templates/ UI pages. This should show:
    - how to create a new page/template.
    - how to register its URLs.
    - how to reuse the base HTML layout to follow the overall web app's styling
    - specific CSS styling unique to buttons, borders, shadows, etc.
    - checking user authentication and role in the HTML template

#### Assigned To: Leon Stansfield
- [x] create the producer dashboard:
    - implement the frontend UI based on the existing style to show a dashboard to the producer listing their products
    - add functionality to add new products with the ability to specify the name, description, unit (if sold in bulk), image, etc..
    - add functionality to remove existing product listings
    - add functionality to modify existing listings
    - limit the producer dashboard view to producers only through user authentication and role verification.
    - tie the developed dashboard with the UI through creating the needed frontend views

#### Assigned To: Amine Ziani
- [x] implement external payment processing
    - decide on an external sandbox payment system for integration and agree with the rest of the team (decided on Stripe)
    - retrieve the needed client secret and key and use to test the API connection to the external service
    - setup the verified connection in the payment gateway API service
- [x] start integrating payment processing with the checkout button in the customer's basket.

## Revised Team Formation

| Role | Service Ownership | Name |
|------|-------------------|-----------------|
| Team Lead | Frontend Service | Matt Wood |
| Developer | Customer Components | Dina Metwalli |
| Developer | Producer Components | Leon Stansfield |
| Developer | Notifications API | Kaan Karadag |
| Developer | Platform API | Kaan Karadag & Matt Wood|
| Developer | Payment Gateway | Amine Ziani |

**Note:** this is the updated structure

## Sprint 1 Deliverables

### 1. Models and Docker Setup
The DB models implemented and a connection to them established in MySQL Workbench. The DB container is running along with all other services according to the refined micro-services project structure.

### 2. Landing Page
A page showing the highlevel view of product listings, with the ability to view each product in further detail individually, and links to login and register with proper error handling

### 3. Customer Shopping Cart
On logging in, customers see the option to view their basekt, add and remove items from it, and clear it. The basket contains an order summary with a checkout button at the bottom

### 4. Producer Dashboard
On logging in, producers see the option to add to, view, edit, and remove their product listings.

### 5. External Payment Mock
Sending a fake payment request to Stripe through the payment service's API to theirs to place a payment and receive confirmation.