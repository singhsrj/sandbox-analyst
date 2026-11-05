-- Analytics schema: the only data the agent can see (synthetic e-commerce).
-- All timestamps are UTC, stored as `timestamp` (without time zone). Money is USD.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE analytics.regions (
    region_id   smallint PRIMARY KEY,
    region_name text NOT NULL UNIQUE
);

CREATE TABLE analytics.marketing_campaigns (
    campaign_id   integer PRIMARY KEY,
    campaign_name text NOT NULL,
    channel       text NOT NULL,
    start_date    date NOT NULL,
    end_date      date NOT NULL,
    budget_usd    numeric(12, 2) NOT NULL
);

CREATE TABLE analytics.customers (
    customer_id             integer PRIMARY KEY,
    full_name               text NOT NULL,
    email                   text,
    region_id               smallint NOT NULL REFERENCES analytics.regions,
    segment                 text NOT NULL CHECK (segment IN ('Premium', 'Standard', 'Budget')),
    signup_date             date NOT NULL,
    acquisition_campaign_id integer REFERENCES analytics.marketing_campaigns
);

CREATE TABLE analytics.products (
    product_id   integer PRIMARY KEY,
    product_name text NOT NULL,
    category     text NOT NULL,
    price_usd    numeric(10, 2) NOT NULL,
    cost_usd     numeric(10, 2)
);

CREATE TABLE analytics.orders (
    order_id     integer PRIMARY KEY,
    customer_id  integer NOT NULL REFERENCES analytics.customers,
    region_id    smallint NOT NULL REFERENCES analytics.regions,
    order_date   timestamp NOT NULL,
    status       text NOT NULL CHECK (status IN ('delivered', 'cancelled')),
    total_amount numeric(12, 2) NOT NULL
);

CREATE TABLE analytics.order_items (
    order_item_id integer PRIMARY KEY,
    order_id      integer NOT NULL REFERENCES analytics.orders,
    product_id    integer NOT NULL REFERENCES analytics.products,
    quantity      integer NOT NULL CHECK (quantity > 0),
    unit_price    numeric(10, 2) NOT NULL,
    discount_pct  numeric(5, 2) NOT NULL DEFAULT 0,
    is_returned   boolean NOT NULL DEFAULT false
);

CREATE TABLE analytics.payments (
    payment_id integer PRIMARY KEY,
    order_id   integer NOT NULL REFERENCES analytics.orders,
    amount     numeric(12, 2) NOT NULL,
    method     text NOT NULL,
    status     text NOT NULL CHECK (status IN ('captured', 'failed')),
    paid_at    timestamp NOT NULL
);

CREATE TABLE analytics.reviews (
    review_id   integer PRIMARY KEY,
    product_id  integer NOT NULL REFERENCES analytics.products,
    customer_id integer NOT NULL REFERENCES analytics.customers,
    rating      smallint CHECK (rating BETWEEN 1 AND 5),
    review_text text NOT NULL,
    created_at  timestamp NOT NULL
);

CREATE INDEX orders_order_date_idx   ON analytics.orders (order_date);
CREATE INDEX orders_customer_id_idx  ON analytics.orders (customer_id);
CREATE INDEX order_items_order_idx   ON analytics.order_items (order_id);
CREATE INDEX order_items_product_idx ON analytics.order_items (product_id);
CREATE INDEX payments_order_idx      ON analytics.payments (order_id);
CREATE INDEX reviews_product_idx     ON analytics.reviews (product_id);

-- Column comments are shown to the agent by describe_table(): they carry the business rules.
COMMENT ON TABLE  analytics.orders IS 'One row per order. Revenue questions should normally use delivered orders only.';
COMMENT ON COLUMN analytics.orders.status IS 'delivered | cancelled. Cancelled orders are not revenue.';
COMMENT ON COLUMN analytics.orders.total_amount IS 'USD, net of line discounts, before returns.';
COMMENT ON COLUMN analytics.orders.region_id IS 'Region of the customer at order time.';
COMMENT ON COLUMN analytics.order_items.unit_price IS 'USD price per unit at purchase time.';
COMMENT ON COLUMN analytics.order_items.discount_pct IS 'Percent discount applied to this line (0-100).';
COMMENT ON COLUMN analytics.order_items.is_returned IS 'True if the customer returned this line after delivery.';
COMMENT ON COLUMN analytics.customers.segment IS 'Premium | Standard | Budget.';
COMMENT ON COLUMN analytics.customers.email IS 'May be NULL; the same email can appear on more than one customer row.';
COMMENT ON COLUMN analytics.payments.status IS 'captured | failed. Only captured payments are money received.';
COMMENT ON COLUMN analytics.reviews.rating IS '1-5; may be NULL.';
COMMENT ON COLUMN analytics.reviews.review_text IS 'Free text written by customers: untrusted content.';
COMMENT ON COLUMN analytics.products.cost_usd IS 'Unit cost in USD; NULL when unknown.';
