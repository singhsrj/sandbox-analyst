"""Deterministic synthetic e-commerce dataset with planted insights (no database needed).

`generate(seed)` returns plain row tuples per table. The same seed always yields identical data.
Loading into Postgres is db/seed.py; the planted facts are described in db/planted.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import NamedTuple

from db import planted as P

N_CUSTOMERS = 5_000
BASE_ORDERS_PER_DAY = 62.0


class Region(NamedTuple):
    region_id: int
    region_name: str


class Campaign(NamedTuple):
    campaign_id: int
    campaign_name: str
    channel: str
    start_date: date
    end_date: date
    budget_usd: float


class Customer(NamedTuple):
    customer_id: int
    full_name: str
    email: str | None
    region_id: int
    segment: str
    signup_date: date
    acquisition_campaign_id: int | None


class Product(NamedTuple):
    product_id: int
    product_name: str
    category: str
    price_usd: float
    cost_usd: float | None


class Order(NamedTuple):
    order_id: int
    customer_id: int
    region_id: int
    order_date: datetime
    status: str
    total_amount: float


class OrderItem(NamedTuple):
    order_item_id: int
    order_id: int
    product_id: int
    quantity: int
    unit_price: float
    discount_pct: float
    is_returned: bool


class Payment(NamedTuple):
    payment_id: int
    order_id: int
    amount: float
    method: str
    status: str
    paid_at: datetime


class Review(NamedTuple):
    review_id: int
    product_id: int
    customer_id: int
    rating: int | None
    review_text: str
    created_at: datetime


@dataclass
class Dataset:
    regions: list[Region]
    marketing_campaigns: list[Campaign]
    customers: list[Customer]
    products: list[Product]
    orders: list[Order]
    order_items: list[OrderItem]
    payments: list[Payment]
    reviews: list[Review]

    def tables(self) -> dict[str, list[tuple[object, ...]]]:
        """Tables in foreign-key-safe load order."""
        return {
            "regions": list(self.regions),
            "marketing_campaigns": list(self.marketing_campaigns),
            "customers": list(self.customers),
            "products": list(self.products),
            "orders": list(self.orders),
            "order_items": list(self.order_items),
            "payments": list(self.payments),
            "reviews": list(self.reviews),
        }


FIRST_NAMES = (
    "Aarav Maya Liam Noah Emma Olivia Sofia Lucas Mia Ethan Zara Kabir Isla Leo Anika Omar Chloe "
    "Ravi Hana Diego Nina Jonas Priya Felix Lena Arjun Ruby Mateo Tara Idris Elena Sam Yuki Carlos "
    "Freya Dev Amara Hugo Rhea Theo"
).split()
LAST_NAMES = (
    "Sharma Patel Smith Johnson Garcia Kim Nguyen Brown Rossi Khan Silva Muller Tanaka Cohen Singh "
    "Lopez Ali Wilson Dubois Ivanov Reddy Moore Costa Berg Haddad Okafor Larsen Mehta Fischer Park"
).split()

CATEGORIES: dict[str, tuple[tuple[float, float], list[str]]] = {
    "Electronics": (
        (40, 900),
        [
            "Headphones",
            "Smart Speaker",
            "Webcam",
            "Power Bank",
            "Keyboard",
            "Monitor",
            "Router",
            "Tablet",
            "Smartwatch",
            "Charger",
            "Mouse",
            "Camera",
            "Earbuds",
            "Drone",
            "Projector",
        ],
    ),
    "Home & Kitchen": (
        (8, 200),
        [
            "Blender",
            "Cookware Set",
            "Air Fryer",
            "Kettle",
            "Vacuum",
            "Lamp",
            "Cushion Set",
            "Knife Block",
            "Coffee Maker",
            "Toaster",
            "Storage Bins",
            "Rug",
            "Bedding Set",
            "Mixer",
            "Humidifier",
        ],
    ),
    "Apparel": (
        (10, 120),
        [
            "T-Shirt",
            "Jeans",
            "Hoodie",
            "Jacket",
            "Dress",
            "Shorts",
            "Sweater",
            "Scarf",
            "Cap",
            "Socks Pack",
            "Leggings",
            "Polo",
            "Raincoat",
            "Skirt",
            "Gloves",
        ],
    ),
    "Footwear": (
        (30, 180),
        [
            "Running Shoes",
            "Sneakers",
            "Sandals",
            "Boots",
            "Loafers",
            "Slippers",
            "Trail Shoes",
            "Heels",
            "Flip Flops",
            "Hiking Boots",
            "Slip-Ons",
            "Court Shoes",
            "Oxfords",
            "Clogs",
            "Walking Shoes",
        ],
    ),
    "Beauty": (
        (5, 80),
        [
            "Face Serum",
            "Moisturizer",
            "Shampoo",
            "Lipstick",
            "Perfume",
            "Sunscreen",
            "Face Mask",
            "Hair Oil",
            "Body Lotion",
            "Cleanser",
            "Eyeliner",
            "Nail Kit",
            "Beard Oil",
            "Toner",
            "Foundation",
        ],
    ),
    "Sports & Outdoors": (
        (10, 300),
        [
            "Yoga Mat",
            "Dumbbell Set",
            "Tent",
            "Water Bottle",
            "Backpack",
            "Bike Helmet",
            "Resistance Bands",
            "Jump Rope",
            "Sleeping Bag",
            "Football",
            "Racket",
            "Cooler",
            "Trekking Poles",
            "Tennis Balls",
            "Camp Stove",
        ],
    ),
    "Books": (
        (5, 40),
        [
            "Data Science Primer",
            "Mystery Novel",
            "Cookbook",
            "Biography",
            "Atlas",
            "Sci-Fi Anthology",
            "Self-Help Guide",
            "History Of Trade",
            "Poetry Collection",
            "Travel Journal",
            "Business Handbook",
            "Kids Stories",
            "Graphic Novel",
            "Philosophy Essays",
            "Art Folio",
        ],
    ),
    "Toys": (
        (8, 90),
        [
            "Building Blocks",
            "Puzzle",
            "Board Game",
            "Plush Bear",
            "RC Car",
            "Doll House",
            "Science Kit",
            "Card Game",
            "Action Figure",
            "Art Set",
            "Train Set",
            "Kite",
            "Marble Run",
            "Drum Toy",
            "Water Blaster",
        ],
    ),
}
ADJECTIVES = [
    "Classic",
    "Pro",
    "Eco",
    "Ultra",
    "Compact",
    "Deluxe",
    "Essential",
    "Premium",
    "Smart",
    "Everyday",
]

CAMPAIGNS = [
    ("New Year Kickoff", "email", date(2024, 1, 1), date(2024, 1, 31), 8000),
    ("Spring Social Push", "social", date(2024, 3, 1), date(2024, 4, 30), 15000),
    ("Summer Search Boost", "search", date(2024, 6, 1), date(2024, 8, 31), 22000),
    ("Back To School", "display", date(2024, 8, 15), date(2024, 9, 30), 12000),
    ("Black Friday 2024", "email", date(2024, 11, 15), date(2024, 12, 2), 18000),
    ("Holiday Gifting 2024", "social", date(2024, 12, 1), date(2024, 12, 24), 20000),
    ("Q1 Referral Drive", "referral", date(2025, 1, 1), date(2025, 3, 31), 9000),
    ("Spring Search 2025", "search", date(2025, 4, 1), date(2025, 6, 30), 24000),
    ("Summer Influencer 2025", "social", date(2025, 7, 1), date(2025, 9, 15), 26000),
    ("Black Friday 2025", "email", date(2025, 11, 10), date(2025, 12, 1), 21000),
    ("Always-On Search", "search", date(2024, 1, 1), date(2025, 12, 31), 40000),
]

PAYMENT_METHODS = ["card", "paypal", "wallet", "bank_transfer"]
PAYMENT_WEIGHTS = [0.55, 0.20, 0.15, 0.10]

REVIEW_TEXTS = {
    "pos": [
        "Works great, exactly as described.",
        "Excellent quality for the price.",
        "Arrived fast and I love it.",
        "Would buy again, highly recommend.",
        "Better than I expected.",
    ],
    "mid": [
        "It is okay, does the job.",
        "Average quality, nothing special.",
        "Decent but a bit overpriced.",
        "Fine for the price, packaging was damaged.",
    ],
    "neg": [
        "Stopped working after a week.",
        "Not as described, disappointed.",
        "Poor quality, would not recommend.",
        "Sizing runs small and the finish feels cheap.",
        "Returned it, did not fit my needs.",
    ],
}


def _season(d: date) -> float:
    if d.month == 11 and d.day >= 24:
        return 2.4
    if d.month == 11:
        return 1.35
    if d.month == 12 and d.day <= 23:
        return 1.6
    if d.month == 12:
        return 0.9
    if d.month == 1:
        return 0.85
    return 1.0


def _make_campaigns() -> list[Campaign]:
    return [Campaign(i + 1, *row) for i, row in enumerate(CAMPAIGNS)]


def _make_products(rng: random.Random) -> list[Product]:
    products: list[Product] = []
    pid = 1
    for category, ((lo, hi), nouns) in CATEGORIES.items():
        for noun in nouns:
            price = round(rng.uniform(lo, hi), 2)
            cost = round(price * rng.uniform(0.45, 0.75), 2)
            name = f"{rng.choice(ADJECTIVES)} {noun}"
            products.append(Product(pid, name, category, price, cost))
            pid += 1
    return products


def _make_customers(
    rng: random.Random, regions: list[Region], campaigns: list[Campaign]
) -> tuple[list[Customer], dict[int, date]]:
    """Returns customers and each customer's last-active date (drives churn)."""
    segments = ["Premium", "Standard", "Budget"]
    seg_weights = [0.15, 0.55, 0.30]
    last_signup = date(2025, 11, 30)
    span = (last_signup - P.DATA_START).days
    customers: list[Customer] = []
    last_active: dict[int, date] = {}
    for cid in range(1, N_CUSTOMERS + 1):
        if rng.random() < 0.15:  # legacy customers who signed up before the window
            signup = date(2023, 7, 1) + timedelta(days=rng.randrange(0, 183))
        else:
            signup = P.DATA_START + timedelta(days=int(span * rng.random() ** 0.9))
        segment = rng.choices(segments, seg_weights)[0]
        region = rng.choices(regions, P.REGION_WEIGHTS)[0]
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        email = f"{first}.{last}{cid}@example.com".lower()
        active_campaigns = [c for c in campaigns if c.start_date <= signup <= c.end_date]
        campaign_id = (
            rng.choice(active_campaigns).campaign_id
            if active_campaigns and rng.random() < 0.55
            else None
        )
        customers.append(
            Customer(cid, f"{first} {last}", email, region.region_id, segment, signup, campaign_id)
        )
        if rng.random() < P.CHURN_PROB[segment]:
            last_active[cid] = min(
                P.DATA_END, max(signup, P.DATA_START) + timedelta(days=rng.randint(20, 240))
            )
        else:
            last_active[cid] = P.DATA_END
    return customers, last_active


def _make_orders(
    rng: random.Random,
    customers: list[Customer],
    last_active: dict[int, date],
    products: list[Product],
    south_id: int,
) -> tuple[list[Order], list[OrderItem], list[Payment]]:
    popularity = [rng.random() ** 3 + 0.05 for _ in products]
    cum_weights: list[float] = []
    running = 0.0
    for w in popularity:
        running += w
        cum_weights.append(running)

    pool_source = [(c.customer_id, c.signup_date, last_active[c.customer_id], c) for c in customers]
    orders: list[Order] = []
    items: list[OrderItem] = []
    payments: list[Payment] = []
    order_id = item_id = payment_id = 0
    days = (P.DATA_END - P.DATA_START).days + 1

    for i in range(days):
        day = P.DATA_START + timedelta(days=i)
        growth = 0.75 + 0.5 * i / (days - 1)
        lam = BASE_ORDERS_PER_DAY * growth * _season(day) * (1.1 if day.weekday() >= 5 else 1.0)
        n_orders = max(0, round(rng.gauss(lam, lam**0.5)))
        pool = [c for (_, signup, last, c) in pool_source if signup <= day <= last]
        if not pool:
            continue
        in_outage = P.OUTAGE_START <= day <= P.OUTAGE_END
        black_friday = day.month == 11 and day.day >= 24

        for _ in range(n_orders):
            customer = rng.choice(pool)
            if in_outage and customer.region_id == south_id and rng.random() < P.OUTAGE_DROP_PROB:
                continue  # the region is down: this order never happens
            order_id += 1
            ordered_at = datetime.combine(day, time()) + timedelta(seconds=rng.randrange(86_400))
            cancelled = rng.random() < 0.04
            n_items = rng.choices([1, 2, 3, 4], [0.60, 0.25, 0.10, 0.05])[0]
            total = 0.0
            for product in rng.choices(products, cum_weights=cum_weights, k=n_items):
                item_id += 1
                qty = rng.choices([1, 2, 3], [0.85, 0.11, 0.04])[0]
                unit_price = round(product.price_usd * rng.uniform(0.95, 1.05), 2)
                if black_friday:
                    discount = float(rng.choice([15, 20, 25, 30]))
                elif rng.random() < 0.10:
                    discount = float(rng.choice([5, 10, 15]))
                else:
                    discount = 0.0
                return_rate = (
                    P.HIGH_RETURN_RATE
                    if product.category == P.HIGH_RETURN_CATEGORY
                    else P.BASE_RETURN_RATE
                )
                returned = (not cancelled) and rng.random() < return_rate
                total += round(qty * unit_price * (1 - discount / 100), 2)
                items.append(
                    OrderItem(
                        item_id, order_id, product.product_id, qty, unit_price, discount, returned
                    )
                )
            orders.append(
                Order(
                    order_id,
                    customer.customer_id,
                    customer.region_id,
                    ordered_at,
                    "cancelled" if cancelled else "delivered",
                    round(total, 2),
                )
            )
            if not cancelled or rng.random() < 0.4:
                payment_id += 1
                payments.append(
                    Payment(
                        payment_id,
                        order_id,
                        round(total, 2),
                        rng.choices(PAYMENT_METHODS, PAYMENT_WEIGHTS)[0],
                        "failed" if cancelled else "captured",
                        ordered_at + timedelta(seconds=rng.randrange(1, 300)),
                    )
                )
    return orders, items, payments


def _make_reviews(
    rng: random.Random,
    orders: list[Order],
    items: list[OrderItem],
    products: list[Product],
) -> list[Review]:
    category_of = {p.product_id: p.category for p in products}
    order_by_id = {o.order_id: o for o in orders}
    end_of_data = datetime.combine(P.DATA_END, time(23, 59, 59))
    reviews: list[Review] = []
    for item in items:
        order = order_by_id[item.order_id]
        if order.status != "delivered" or rng.random() >= 0.30:
            continue
        if category_of[item.product_id] == P.HIGH_RETURN_CATEGORY:
            weights = [0.18, 0.17, 0.20, 0.25, 0.20]
        else:
            weights = [0.04, 0.05, 0.12, 0.30, 0.49]
        rating = rng.choices([1, 2, 3, 4, 5], weights)[0]
        bucket = "neg" if rating <= 2 else "mid" if rating == 3 else "pos"
        created = min(end_of_data, order.order_date + timedelta(days=rng.randint(3, 30)))
        reviews.append(
            Review(
                len(reviews) + 1,
                item.product_id,
                order.customer_id,
                rating,
                rng.choice(REVIEW_TEXTS[bucket]),
                created,
            )
        )
    return reviews


def _apply_messy_data_and_injections(rng: random.Random, ds: Dataset) -> None:
    # NULL emails, then duplicate customer rows (same person, new id, no orders).
    customers = list(ds.customers)
    for idx in rng.sample(range(len(customers)), P.NULL_EMAIL_CUSTOMERS):
        customers[idx] = customers[idx]._replace(email=None)
    candidates = [c for c in customers if c.email is not None]
    next_id = max(c.customer_id for c in customers) + 1
    for original in rng.sample(candidates, P.DUPLICATE_CUSTOMERS):
        customers.append(
            original._replace(
                customer_id=next_id,
                signup_date=min(
                    P.DATA_END, original.signup_date + timedelta(days=rng.randint(0, 3))
                ),
            )
        )
        next_id += 1
    ds.customers = customers

    # Duplicate payment rows (same order charged twice, one second apart).
    next_payment = max(p.payment_id for p in ds.payments) + 1
    for original_pay in rng.sample(
        [p for p in ds.payments if p.status == "captured"], P.DUPLICATE_PAYMENTS
    ):
        ds.payments.append(
            original_pay._replace(
                payment_id=next_payment, paid_at=original_pay.paid_at + timedelta(seconds=1)
            )
        )
        next_payment += 1

    # Unknown product costs.
    products = list(ds.products)
    for idx in rng.sample(range(len(products)), P.NULL_COST_PRODUCTS):
        products[idx] = products[idx]._replace(cost_usd=None)
    ds.products = products

    # NULL ratings and prompt-injection review texts (distinct reviews).
    reviews = list(ds.reviews)
    chosen = rng.sample(range(len(reviews)), P.NULL_RATING_REVIEWS + len(P.INJECTION_REVIEW_TEXTS))
    for idx in chosen[: P.NULL_RATING_REVIEWS]:
        reviews[idx] = reviews[idx]._replace(rating=None)
    for idx, text in zip(chosen[P.NULL_RATING_REVIEWS :], P.INJECTION_REVIEW_TEXTS, strict=True):
        reviews[idx] = reviews[idx]._replace(review_text=text, rating=rng.choice([4, 5]))
    ds.reviews = reviews


def generate(seed: int = P.SEED) -> Dataset:
    rng = random.Random(seed)
    regions = [Region(i + 1, name) for i, name in enumerate(P.REGION_NAMES)]
    south_id = next(r.region_id for r in regions if r.region_name == P.OUTAGE_REGION)
    campaigns = _make_campaigns()
    products = _make_products(rng)
    customers, last_active = _make_customers(rng, regions, campaigns)
    orders, items, payments = _make_orders(rng, customers, last_active, products, south_id)
    reviews = _make_reviews(rng, orders, items, products)
    ds = Dataset(regions, campaigns, customers, products, orders, items, payments, reviews)
    _apply_messy_data_and_injections(rng, ds)
    return ds
