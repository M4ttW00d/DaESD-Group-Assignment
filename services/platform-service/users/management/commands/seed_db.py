from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
import datetime
import math
import requests as http_requests

def _seed_get_coords(postcode, cache={}):
    key = postcode.strip().upper().replace(' ', '')
    if key in cache:
        return cache[key]
    try:
        resp = http_requests.get(
            f"https://api.postcodes.io/postcodes/{postcode.strip().replace(' ', '%20')}",
            timeout=5
        )
        if resp.status_code == 200:
            r = resp.json().get('result') or {}
            coords = r.get('latitude'), r.get('longitude')
            cache[key] = coords
            return coords
    except Exception:
        pass
    cache[key] = (None, None)
    return None, None

def _seed_food_miles(customer_postcode, producer_postcode):
    if not customer_postcode or not producer_postcode:
        return None
    lat1, lon1 = _seed_get_coords(customer_postcode)
    lat2, lon2 = _seed_get_coords(producer_postcode)
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return round(R * 2 * math.asin(math.sqrt(a)), 1)

from users.models import ProducerProfile, CustomerProfile
from products.models import Category, Product, Recipe, FarmStory
from orders.models import Order, OrderItem, CustomerOrder
from reviews.models import Review

User = get_user_model()


class Command(BaseCommand):
    help = 'Seeds the database with realistic test data for the South West regional food network.'

    def handle(self, *args, **kwargs):
        self.stdout.write('Clearing existing data...')
        self._clear()
        self.stdout.write(self.style.SUCCESS('Done.'))

        self.stdout.write('Seeding...')
        categories = self._seed_categories()
        producers = self._seed_producers()
        customers = self._seed_customers()
        products = self._seed_products(producers, categories)
        self._seed_content(producers, products)
        self._seed_orders(producers, customers, products)
        self.stdout.write(self.style.SUCCESS('Database seeded successfully.'))

    def _clear(self):
        Review.objects.all().delete()
        OrderItem.all_objects.all().delete()
        Order.all_objects.all().delete()
        CustomerOrder.objects.all().delete()
        Recipe.objects.all().delete()
        FarmStory.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

    def _seed_categories(self):
        names = ['Vegetables', 'Fruits', 'Dairy', 'Bakery', 'Meat', 'Eggs', 'Preserves', 'Drinks']
        cats = {}
        for name in names:
            c, _ = Category.objects.get_or_create(name=name)
            cats[name] = c
        self.stdout.write(self.style.SUCCESS(f'  {len(cats)} categories'))
        return cats

    def _seed_producers(self):
        data = [
            {
                'username': 'riverford',
                'email': 'hello@riverford.co.uk',
                'phone_number': '01803762059',
                'business_name': 'Riverford Organic Farm',
                'business_address': 'Wash Barn, Buckfastleigh, Devon',
                'postcode': 'TQ11 0JU',
                'bio': (
                    'We have been growing organic vegetables in Devon since 1987. '
                    'Everything is picked fresh and delivered in our iconic veg boxes. '
                    'Our farm covers 650 acres across the South Hams.'
                ),
            },
            {
                'username': 'washingpool',
                'email': 'info@washingpoolfarm.co.uk',
                'phone_number': '01308423060',
                'business_name': 'Washingpool Farm',
                'business_address': 'North Allington, Bridport, Dorset',
                'postcode': 'DT6 3HP',
                'bio': (
                    'A family-run farm on the Dorset coast growing award-winning vegetables, '
                    'salads and herbs. We have been farming this land for over 30 years '
                    'and supply local restaurants and markets across West Dorset.'
                ),
            },
            {
                'username': 'sharpham',
                'email': 'cheese@sharpham.com',
                'phone_number': '01803732600',
                'business_name': 'Sharpham Dairy',
                'business_address': 'Sharpham Estate, Totnes, Devon',
                'postcode': 'TQ9 7UT',
                'bio': (
                    'The Sharpham Estate sits on a dramatic bend in the River Dart. '
                    'Our herd of Jersey cows grazes the riverside meadows year round, '
                    'producing rich milk we turn into award-winning cheeses and clotted cream.'
                ),
            },
            {
                'username': 'greenacres_bakery',
                'email': 'bake@greenacresbakery.co.uk',
                'phone_number': '01225442210',
                'business_name': 'Green Acres Bakery',
                'business_address': '14 Larkhall Rise, Bath',
                'postcode': 'BA1 6PT',
                'bio': (
                    'A small artisan bakery in Bath using stoneground flour from Shipton Mill '
                    'and locally sourced ingredients. We bake overnight for morning freshness '
                    'and have been supplying Bath since 2009.'
                ),
            },
            {
                'username': 'barrow_boar',
                'email': 'orders@barrowboar.co.uk',
                'phone_number': '01460240249',
                'business_name': 'Barrow Boar',
                'business_address': 'Higher Barrow Farm, South Petherton, Somerset',
                'postcode': 'TA13 5LR',
                'bio': (
                    'We raise free-range pigs and wild boar on our Somerset farm. '
                    'Our animals are born and reared outdoors with plenty of space to roam. '
                    'We process everything on-site and sell direct to customers across the region.'
                ),
            },
        ]

        producers = []
        for d in data:
            u, created = User.objects.get_or_create(
                username=d['username'],
                defaults={
                    'email': d['email'],
                    'role': 'PRODUCER',
                    'phone_number': d['phone_number'],
                }
            )
            if created:
                u.set_password('password123')
                u.save()
                ProducerProfile.objects.create(
                    user=u,
                    business_name=d['business_name'],
                    business_address=d['business_address'],
                    postcode=d['postcode'],
                    bio=d['bio'],
                )
            producers.append(u)

        self.stdout.write(self.style.SUCCESS(f'  {len(producers)} producers'))
        return producers

    def _seed_customers(self):
        data = [
            {
                'username': 'sarah_j',
                'email': 'sarah.jones@gmail.com',
                'first_name': 'Sarah',
                'last_name': 'Jones',
                'delivery_address': '14 Clifton Down Road, Bristol',
                'postcode': 'BS8 4AN',
            },
            {
                'username': 'tom_b',
                'email': 'tom.baker@outlook.com',
                'first_name': 'Tom',
                'last_name': 'Baker',
                'delivery_address': '3 Milsom Street, Bath',
                'postcode': 'BA1 1BZ',
            },
            {
                'username': 'priya_k',
                'email': 'priya.k@hotmail.co.uk',
                'first_name': 'Priya',
                'last_name': 'Kapoor',
                'delivery_address': '22 Fore Street, Exeter',
                'postcode': 'EX4 3AN',
            },
            {
                'username': 'james_w',
                'email': 'james.walsh@yahoo.co.uk',
                'first_name': 'James',
                'last_name': 'Walsh',
                'delivery_address': '8 Westgate Street, Gloucester',
                'postcode': 'GL1 2NW',
            },
            {
                'username': 'emma_r',
                'email': 'emma.riley@gmail.com',
                'first_name': 'Emma',
                'last_name': 'Riley',
                'delivery_address': '5 High Street, Taunton',
                'postcode': 'TA1 3PJ',
            },
        ]

        customers = []
        for d in data:
            u, created = User.objects.get_or_create(
                username=d['username'],
                defaults={
                    'email': d['email'],
                    'role': 'CUSTOMER',
                    'phone_number': '07700900000',
                }
            )
            if created:
                u.set_password('password123')
                u.save()
                CustomerProfile.objects.create(
                    user=u,
                    first_name=d['first_name'],
                    last_name=d['last_name'],
                    delivery_address=d['delivery_address'],
                    postcode=d['postcode'],
                )
            customers.append(u)

        self.stdout.write(self.style.SUCCESS(f'  {len(customers)} customers'))
        return customers

    def _seed_products(self, producers, cats):
        today = timezone.now().date()
        riverford, washingpool, sharpham, bakery, barrow = producers

        all_products = []

        def make(producer, name, cat, price, unit, stock, organic, allergens, desc,
                 harvest=None, best_before=None, seasonal_start=None, seasonal_end=None,
                 image=None):
            p, _ = Product.objects.get_or_create(
                name=name,
                producer=producer,
                defaults=dict(
                    category=cats[cat],
                    description=desc,
                    price=Decimal(str(price)),
                    unit=unit,
                    stock_quantity=stock,
                    is_organic=organic,
                    is_available=True,
                    allergens=allergens,
                    harvest_date=harvest,
                    best_before_date=best_before,
                    seasonal_start_month=seasonal_start,
                    seasonal_end_month=seasonal_end,
                    image=image or '',
                )
            )
            all_products.append(p)
            return p

        # Riverford
        make(riverford, 'Carrots', 'Vegetables', 1.80, 'kg', 200, True, [],
             'Unwashed Chantenay carrots straight from the field. Sweet and earthy.',
             harvest=today - datetime.timedelta(days=2), image='products/carrot.jpg')
        make(riverford, 'Broccoli', 'Vegetables', 1.50, 'head', 80, True, [],
             'Tight purple sprouting broccoli, harvested to order.',
             harvest=today - datetime.timedelta(days=1), seasonal_start=2, seasonal_end=4)
        make(riverford, 'Leeks', 'Vegetables', 2.20, 'bunch', 60, True, [],
             'Long slender leeks with a mild flavour. Great for soups and gratins.',
             harvest=today - datetime.timedelta(days=3), seasonal_start=10, seasonal_end=3)
        make(riverford, 'Courgettes', 'Vegetables', 1.90, 'kg', 100, True, [],
             'Tender green courgettes, best eaten young. Grown in polytunnels.',
             harvest=today - datetime.timedelta(days=1), seasonal_start=6, seasonal_end=9)
        make(riverford, 'Butternut Squash', 'Vegetables', 2.50, 'each', 50, True, [],
             'Stored from the autumn harvest. Dense sweet flesh, keeps for months.',
             harvest=today - datetime.timedelta(days=30))
        make(riverford, 'Spinach', 'Vegetables', 1.60, '200g bag', 70, True, [],
             'Baby leaf spinach, washed and ready. Picked the same morning.',
             harvest=today)

        # Washingpool
        make(washingpool, 'Mixed Salad Leaves', 'Vegetables', 2.00, '100g bag', 40, False, [],
             'A blend of rocket, watercress, red chard and oak leaf lettuce.',
             harvest=today)
        make(washingpool, 'Heritage Tomatoes', 'Vegetables', 3.50, '500g', 35, False, [],
             'A mix of Tigerella, Black Krim and Sungold tomatoes. Complex flavour.',
             harvest=today - datetime.timedelta(days=1), seasonal_start=7, seasonal_end=10)
        make(washingpool, 'Garlic', 'Vegetables', 3.00, 'bulb', 120, False, [],
             'Cured Dorset garlic, strong and full-flavoured. Lasts for months in a cool dry place.',
             harvest=today - datetime.timedelta(days=60))
        make(washingpool, 'New Potatoes', 'Vegetables', 2.80, 'kg', 150, False, [],
             'Jersey Royal-style new potatoes grown in Dorset. Waxy and buttery.',
             harvest=today - datetime.timedelta(days=4), seasonal_start=5, seasonal_end=8)
        make(washingpool, 'Strawberries', 'Fruits', 3.20, '250g punnet', 45, False, [],
             'Elsanta strawberries grown in outdoor beds. No polytunnels.',
             harvest=today - datetime.timedelta(days=1), seasonal_start=6, seasonal_end=8)
        make(washingpool, 'Raspberries', 'Fruits', 3.80, '150g punnet', 30, False, [],
             'Glen Ample raspberries, picked at full ripeness.',
             harvest=today, seasonal_start=7, seasonal_end=9)

        # Sharpham
        make(sharpham, 'Sharpham Rustic', 'Dairy', 6.50, '200g', 25, False, ['Milk'],
             'A soft unpasteurised cheese with a wrinkled rind and rich buttery flavour. '
             'Made from the milk of our Jersey herd.')
        make(sharpham, 'Clotted Cream', 'Dairy', 3.00, '113g pot', 40, False, ['Milk'],
             'Traditional Devon clotted cream, scalded slowly to form the golden crust. '
             'The only way to serve a scone.')
        make(sharpham, 'Jersey Full Fat Milk', 'Dairy', 1.80, 'pint', 60, False, ['Milk'],
             'Unhomogenised Jersey milk with a thick cream line. Collected from our herd daily.',
             image='products/milk.jpg')
        make(sharpham, 'Creme Fraiche', 'Dairy', 2.40, '200ml', 30, False, ['Milk'],
             'Thick and slightly tangy, made from our Jersey cream.')
        make(sharpham, 'Whey Butter', 'Dairy', 4.50, '200g', 20, False, ['Milk'],
             'Cultured butter churned from whey cream, with a pronounced tang.')

        # Bakery
        make(bakery, 'Sourdough Tin Loaf', 'Bakery', 4.50, 'loaf', 15, False,
             ['Cereals containing gluten'],
             'Long-fermented sourdough using Shipton Mill stoneground white flour. '
             '18-hour cold prove.',
             image='products/bread.jpg')
        make(bakery, 'Seeded Rye', 'Bakery', 5.00, 'loaf', 10, False,
             ['Cereals containing gluten', 'Sesame'],
             'Dense rye bread with sunflower, pumpkin and sesame seeds. '
             'Keeps well for up to a week.')
        make(bakery, 'Cinnamon Buns', 'Bakery', 2.80, 'each', 20, False,
             ['Cereals containing gluten', 'Milk', 'Eggs'],
             'Enriched dough rolled with brown butter and cinnamon, finished with cream cheese icing.')
        make(bakery, 'Cheese and Chive Scones', 'Bakery', 1.80, 'each', 24, False,
             ['Cereals containing gluten', 'Milk', 'Eggs'],
             'Made with Montgomery Cheddar and fresh chives from our window boxes.')
        make(bakery, 'Focaccia', 'Bakery', 3.50, 'slab', 12, False,
             ['Cereals containing gluten'],
             'Dimpled focaccia with Maldon sea salt and rosemary, baked in olive oil.')

        # Barrow Boar
        make(barrow, 'Pork Sausages', 'Meat', 5.50, '400g pack', 30, False, [],
             'Six thick pork sausages made from our free-range Landrace cross pigs. '
             'Seasoned with sage and white pepper.')
        make(barrow, 'Back Bacon', 'Meat', 4.80, '250g pack', 25, False, [],
             'Dry-cured back bacon from our outdoor-reared pigs. Smoked over oak chips.')
        make(barrow, 'Wild Boar Burgers', 'Meat', 7.50, '2 pack', 20, False, [],
             'Coarse-ground wild boar patties, seasoned simply with salt and juniper.')
        make(barrow, 'Pork Belly Slices', 'Meat', 6.00, '500g', 15, False, [],
             'Thick cut pork belly from slow-grown outdoor pigs. Ideal for slow roasting.')
        make(barrow, 'Saucisson Sec', 'Meat', 8.00, 'whole', 10, False, [],
             'Air-dried pork salami in the French style, made in our Somerset curing room.')

        self.stdout.write(self.style.SUCCESS(f'  {len(all_products)} products'))
        return all_products

    def _seed_content(self, producers, products):
        riverford, washingpool, sharpham, bakery, barrow = producers

        stories = [
            (riverford, 'A late start to the carrot harvest',
             'This year the wet spring pushed our carrot harvest back by almost three weeks. '
             'The fields at Wash Barn held too much water through April and we had to wait for '
             'the ground to firm before the tractor could get in. It was frustrating at the time '
             'but the extra time in the ground has meant the flavour is exceptional — '
             'sweeter than most years and with real depth. We started lifting last week and '
             'the crop looks strong.'),
            (washingpool, 'Why we stopped using polytunnels for salad',
             'Three years ago we made the decision to stop growing our salad leaves under cover. '
             'The flavour of outdoor-grown leaves is simply better — more mineral, more bitter, '
             'more interesting. The trade-off is a shorter season and more risk from the weather, '
             'but we think it is worth it. Our customers seem to agree.'),
            (sharpham, 'The Jersey herd in January',
             'January is a quiet month on the dairy. The cows spend the coldest weeks in the barns '
             'with ad lib hay and a little silage. Milk yields drop naturally at this time of year '
             'as the cows rest before calving season begins in February. The cream is still rich '
             'though — if anything richer than in summer — because the cows are eating more conserved grass.'),
            (bakery, 'Switching to long fermentation',
             'We changed our process in 2021 to use an 18-hour cold fermentation for all our '
             'sourdoughs. The difference was immediate — better crust, more complex flavour, '
             'and bread that keeps noticeably longer. It means we have to plan further ahead '
             'but the results justify it completely.'),
            (barrow, 'The wild boar farrowing season',
             'March is always hectic on the farm. The wild boar sows farrow outdoors in the '
             'woodland paddock and need careful watching — wild boar are attentive mothers '
             'but the piglets are tiny and vulnerable in the first few days. '
             'This year we had seven litters, all healthy. The piglets will run with their '
             'mothers until late summer before being moved to the finishing paddocks.'),
        ]

        for producer, title, content in stories:
            FarmStory.objects.get_or_create(
                producer=producer,
                title=title,
                defaults={'content': content}
            )

        def get_product(name, producer):
            return Product.objects.filter(name=name, producer=producer).first()

        recipes = [
            (riverford, 'Roasted carrot and lentil soup',
             'A warming winter soup that makes the most of sweet roasted carrots.',
             '- 1kg Carrots\n- 200g red lentils\n- 1 onion\n- 2 cloves garlic\n'
             '- 1 tsp cumin\n- 1 tsp coriander\n- 1 litre vegetable stock\n- Olive oil',
             '1. Roast carrots with olive oil at 200C for 25 minutes.\n'
             '2. Soften onion and garlic in a large pan.\n'
             '3. Add spices and cook for 1 minute.\n'
             '4. Add lentils, roasted carrots and stock.\n'
             '5. Simmer for 20 minutes then blend until smooth.',
             'Autumn/Winter',
             [get_product('Carrots', riverford)]),
            (sharpham, 'Classic Devon cream tea',
             'The definitive guide to assembling a proper cream tea.',
             '- 2 scones\n- Sharpham clotted cream\n- Good strawberry jam\n- Loose leaf Assam tea',
             '1. Split the scones in half.\n'
             '2. Spread with jam to the edges.\n'
             '3. Add a generous spoonful of clotted cream on top.\n'
             '4. Brew tea at 90C and pour.',
             'All year',
             [get_product('Clotted Cream', sharpham)]),
            (bakery, 'Sourdough tartine with butter and radishes',
             'A simple open sandwich that lets good bread and good butter do the talking.',
             '- 2 thick slices sourdough\n- Butter\n- 6 radishes, thinly sliced\n- Sea salt\n- Chives',
             '1. Toast sourdough slices lightly.\n'
             '2. Spread thickly with butter.\n'
             '3. Layer over sliced radishes.\n'
             '4. Finish with sea salt and snipped chives.',
             'Spring/Summer',
             [get_product('Sourdough Tin Loaf', bakery)]),
            (barrow, 'Wild boar burger with roasted garlic aioli',
             'A straightforward burger recipe that keeps the focus on the quality of the meat.',
             '- 2 wild boar burgers\n- 2 brioche buns\n- 1 head garlic\n'
             '- 2 egg yolks\n- 150ml olive oil\n- Lemon juice\n- Gem lettuce',
             '1. Roast the whole garlic head at 180C for 40 minutes.\n'
             '2. Squeeze out the soft cloves and blend with egg yolks.\n'
             '3. Slowly whisk in olive oil to make aioli. Season with lemon and salt.\n'
             '4. Grill burgers for 4 minutes each side.\n'
             '5. Toast buns, build with lettuce, burger and aioli.',
             'All year',
             [get_product('Wild Boar Burgers', barrow)]),
        ]

        for producer, title, desc, ingredients, instructions, season, linked_products in recipes:
            recipe, _ = Recipe.objects.get_or_create(
                producer=producer,
                title=title,
                defaults={
                    'description': desc,
                    'ingredients': ingredients,
                    'instructions': instructions,
                    'season_tag': season,
                }
            )
            for p in linked_products:
                if p:
                    recipe.products.add(p)

        self.stdout.write(self.style.SUCCESS('  Farm stories and recipes created'))

    def _seed_orders(self, producers, customers, products):
        today = timezone.now().date()
        riverford, washingpool, sharpham, bakery, barrow = producers
        sarah, tom, priya, james, emma = customers

        order_specs = [
            # DELIVERED
            (sarah, [(riverford, ['Carrots', 'Spinach', 'Broccoli'], 1, 'Delivery'),
                     (sharpham, ['Jersey Full Fat Milk', 'Clotted Cream'], 2, 'Delivery')], 'DELIVERED', 90),
            (tom, [(bakery, ['Sourdough Tin Loaf', 'Cheese and Chive Scones'], 2, 'Delivery')], 'DELIVERED', 85),
            (priya, [(riverford, ['Butternut Squash', 'Leeks'], 1, 'Delivery'),
                     (barrow, ['Pork Sausages', 'Back Bacon'], 1, 'Delivery')], 'DELIVERED', 80),
            (james, [(washingpool, ['Garlic', 'Heritage Tomatoes'], 2, 'Collection')], 'DELIVERED', 75),
            (emma, [(sharpham, ['Sharpham Rustic', 'Whey Butter'], 1, 'Delivery'),
                    (bakery, ['Sourdough Tin Loaf', 'Focaccia'], 1, 'Delivery')], 'DELIVERED', 70),
            (sarah, [(barrow, ['Wild Boar Burgers', 'Pork Belly Slices'], 1, 'Delivery')], 'DELIVERED', 65),
            (tom, [(riverford, ['Courgettes', 'Spinach'], 2, 'Collection'),
                   (washingpool, ['Strawberries', 'Raspberries'], 1, 'Delivery')], 'DELIVERED', 60),
            (priya, [(bakery, ['Cinnamon Buns', 'Seeded Rye'], 3, 'Delivery')], 'DELIVERED', 55),
            (james, [(riverford, ['Carrots', 'Leeks'], 2, 'Delivery'),
                     (sharpham, ['Clotted Cream', 'Creme Fraiche'], 1, 'Delivery')], 'DELIVERED', 50),
            (emma, [(barrow, ['Saucisson Sec', 'Back Bacon'], 1, 'Collection')], 'DELIVERED', 45),
            (sarah, [(washingpool, ['Mixed Salad Leaves', 'Heritage Tomatoes', 'Garlic'], 1, 'Delivery')], 'DELIVERED', 40),
            (tom, [(riverford, ['Broccoli', 'Leeks', 'Butternut Squash'], 1, 'Delivery'),
                   (barrow, ['Pork Sausages'], 2, 'Delivery')], 'DELIVERED', 35),
            (priya, [(sharpham, ['Jersey Full Fat Milk', 'Whey Butter'], 2, 'Delivery')], 'DELIVERED', 30),
            (james, [(bakery, ['Focaccia', 'Seeded Rye'], 1, 'Delivery')], 'DELIVERED', 25),
            (emma, [(riverford, ['Spinach', 'Courgettes'], 2, 'Delivery'),
                    (washingpool, ['New Potatoes', 'Garlic'], 1, 'Delivery')], 'DELIVERED', 20),
            # READY
            (priya, [(sharpham, ['Sharpham Rustic', 'Jersey Full Fat Milk'], 1, 'Delivery')], 'READY', 5),
            (james, [(bakery, ['Sourdough Tin Loaf', 'Focaccia'], 2, 'Delivery'),
                     (riverford, ['Spinach', 'Carrots'], 1, 'Delivery')], 'READY', 4),
            # CONFIRMED
            (emma, [(riverford, ['Courgettes', 'Spinach'], 2, 'Delivery')], 'CONFIRMED', 3),
            (sarah, [(barrow, ['Wild Boar Burgers', 'Pork Belly Slices'], 1, 'Delivery'),
                     (washingpool, ['Raspberries', 'Strawberries'], 2, 'Delivery')], 'CONFIRMED', 2),
            (tom, [(sharpham, ['Clotted Cream', 'Whey Butter'], 1, 'Collection')], 'CONFIRMED', 2),
            # PENDING
            (priya, [(bakery, ['Cinnamon Buns', 'Cheese and Chive Scones'], 4, 'Delivery')], 'PENDING', 1),
            (james, [(riverford, ['Carrots', 'Broccoli', 'Spinach'], 1, 'Delivery'),
                     (barrow, ['Back Bacon', 'Saucisson Sec'], 1, 'Delivery')], 'PENDING', 1),
            (emma, [(washingpool, ['Mixed Salad Leaves', 'Garlic'], 2, 'Delivery')], 'PENDING', 0),
            (sarah, [(sharpham, ['Jersey Full Fat Milk', 'Creme Fraiche'], 3, 'Collection')], 'PENDING', 0),
        ]

        order_count = 0
        for customer, producer_groups, status, days_ago in order_specs:
            order_date = timezone.now() - datetime.timedelta(days=days_ago)
            delivery_date = today + datetime.timedelta(days=2)

            customer_order = CustomerOrder.objects.create(
                customer=customer,
                total_amount=Decimal('0.00'),
                commission_total=Decimal('0.00'),
            )
            CustomerOrder.objects.filter(pk=customer_order.pk).update(created_at=order_date)

            customer_total = Decimal('0.00')
            customer_commission = Decimal('0.00')

            for producer, product_names, qty, collection_type in producer_groups:
                order_delivery_date = (
                    delivery_date if status in ('PENDING', 'CONFIRMED', 'READY')
                    else today - datetime.timedelta(days=max(days_ago - 2, 1))
                )

                # Calculate food miles for delivery orders only
                food_miles = None
                if 'collect' not in collection_type.lower():
                    try:
                        customer_postcode = customer.customer_profile.postcode
                        producer_postcode = producer.producer_profile.postcode
                        food_miles = _seed_food_miles(customer_postcode, producer_postcode)
                    except Exception:
                        pass

                order = Order.objects.create(
                    customer=customer,
                    customer_order=customer_order,
                    producer=producer,
                    status=status,
                    delivery_date=order_delivery_date,
                    collection_type=collection_type,
                    food_miles=food_miles,
                    total_amount=Decimal('0.00'),
                    commission_total=Decimal('0.00'),
                )
                Order.all_objects.filter(pk=order.pk).update(created_at=order_date)

                order_total = Decimal('0.00')
                for name in product_names:
                    try:
                        prod = Product.objects.get(name=name, producer=producer)
                    except Product.DoesNotExist:
                        self.stdout.write(self.style.WARNING(f'  Product not found: {name} by {producer.username}'))
                        continue
                    OrderItem.objects.create(
                        order=order,
                        product=prod,
                        quantity=qty,
                        price_at_sale=prod.price,
                    )
                    order_total += prod.price * qty

                commission = (order_total * Decimal('0.05')).quantize(Decimal('0.01'))
                Order.all_objects.filter(pk=order.pk).update(
                    total_amount=order_total,
                    commission_total=commission,
                    producer_payout=order_total - commission,
                )
                customer_total += order_total
                customer_commission += commission

            CustomerOrder.objects.filter(pk=customer_order.pk).update(
                total_amount=customer_total,
                commission_total=customer_commission,
            )
            order_count += 1

        self.stdout.write(self.style.SUCCESS(f'  {order_count} customer orders created'))

        review_data = [
            (customers[0], 'Carrots', riverford, 5, 'Excellent quality, really sweet. Will order again.'),
            (customers[0], 'Clotted Cream', sharpham, 5, 'Proper Devon cream. Thick golden crust, rich and not overly sweet.'),
            (customers[1], 'Sourdough Tin Loaf', bakery, 4, 'Good crust and a nice open crumb. Keeps well for three days.'),
            (customers[2], 'Pork Sausages', barrow, 5, 'The best sausages I have bought outside of a butcher.'),
            (customers[3], 'Heritage Tomatoes', washingpool, 4, 'Beautiful colours and much better flavour than supermarket tomatoes.'),
            (customers[4], 'Sharpham Rustic', sharpham, 5, 'Exceptional cheese. Creamy with a slightly sharp finish.'),
            (customers[0], 'Wild Boar Burgers', barrow, 4, 'Rich and gamey. Cooked them simply and they were superb.'),
            (customers[1], 'Courgettes', riverford, 3, 'Good quality but slightly smaller than expected.'),
            (customers[2], 'Cinnamon Buns', bakery, 5, 'These are extraordinary. Best baked goods I have had delivered.'),
            (customers[3], 'Jersey Full Fat Milk', sharpham, 5, 'You can see the cream line before you even open the bottle.'),
        ]

        review_count = 0
        for customer, product_name, producer, rating, comment in review_data:
            try:
                product = Product.objects.get(name=product_name, producer=producer)
                Review.objects.get_or_create(
                    customer=customer,
                    product=product,
                    defaults={'rating': rating, 'comment': comment, 'title': ''}
                )
                review_count += 1
            except Product.DoesNotExist:
                pass

        self.stdout.write(self.style.SUCCESS(f'  {review_count} reviews created'))
