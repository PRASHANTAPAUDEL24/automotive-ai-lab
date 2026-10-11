DROP TABLE IF EXISTS inventory_snapshot, leads_monthly, dealer_targets,
                     sales_monthly, vehicle_models, dealers CASCADE;

CREATE TABLE dealers (
    dealer_id    INTEGER PRIMARY KEY,
    dealer_name  TEXT NOT NULL,
    city         TEXT NOT NULL,
    state        CHAR(2) NOT NULL,
    region       TEXT NOT NULL,
    size_class   TEXT NOT NULL,
    opened_year  INTEGER
);

CREATE TABLE vehicle_models (
    model    TEXT PRIMARY KEY,
    segment  TEXT NOT NULL,
    msrp     INTEGER NOT NULL
);

CREATE TABLE sales_monthly (
    dealer_id       INTEGER NOT NULL REFERENCES dealers(dealer_id),
    month           TEXT NOT NULL,
    model           TEXT NOT NULL REFERENCES vehicle_models(model),
    units_sold      INTEGER NOT NULL,
    avg_sale_price  NUMERIC,
    PRIMARY KEY (dealer_id, month, model)
);

CREATE TABLE dealer_targets (
    dealer_id     INTEGER NOT NULL REFERENCES dealers(dealer_id),
    month         TEXT NOT NULL,
    target_units  INTEGER NOT NULL,
    PRIMARY KEY (dealer_id, month)
);

CREATE TABLE leads_monthly (
    dealer_id    INTEGER NOT NULL REFERENCES dealers(dealer_id),
    month        TEXT NOT NULL,
    leads        INTEGER NOT NULL,
    test_drives  INTEGER NOT NULL,
    PRIMARY KEY (dealer_id, month)
);

CREATE TABLE inventory_snapshot (
    vin            TEXT PRIMARY KEY,
    dealer_id      INTEGER NOT NULL REFERENCES dealers(dealer_id),
    model          TEXT NOT NULL REFERENCES vehicle_models(model),
    trim           TEXT,
    color          TEXT,
    msrp           INTEGER,
    received_date  DATE,
    days_in_stock  INTEGER NOT NULL,
    status         TEXT NOT NULL
);