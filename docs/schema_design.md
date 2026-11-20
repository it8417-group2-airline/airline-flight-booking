SCHEMA: mainline_carrier  (normalised – 6 tables)

TABLE: airport
- airport_code       CHAR(3)        PK            (IATA code, e.g. BAH)
- airport_name       VARCHAR(120)   NOT NULL
- city               VARCHAR(80)    NOT NULL
- country_code       CHAR(2)        NOT NULL      (e.g. BH)
- is_hub             BOOLEAN                      (TRUE for BAH)
- timezone_name      VARCHAR(40)    (operational only – ETL drops)
- terminal_count     SMALLINT       (operational only – ETL drops)
Why: airport details stored once; flights point to them by code.

TABLE: cabin_class
- cabin_class_id     SMALLINT       PK
- cabin_code         CHAR(1)        UNIQUE        (Y, W, J, F)
- cabin_name         VARCHAR(30)    UNIQUE
- fare_multiplier    NUMERIC(4,2)   NOT NULL      (1.00, 1.45, 2.60, 4.10)
- lounge_access_code VARCHAR(10)    (operational only – ETL drops)
- display_colour     VARCHAR(7)     (operational only – ETL drops)
Why: "Business" stored once, so no spelling mistakes (regional schema uses free text instead).

TABLE: passenger
- passenger_id       SERIAL         PK
- first_name         VARCHAR(60)    NOT NULL
- last_name          VARCHAR(60)    NOT NULL
- email              VARCHAR(120)   UNIQUE
- date_of_birth      DATE
- nationality        CHAR(2)
- frequent_flyer_no  VARCHAR(12)
- phone              VARCHAR(20)    (operational only – ETL drops)
- passport_scan_ref  VARCHAR(40)    (operational only – ETL drops)
- created_at         TIMESTAMPTZ    DEFAULT now()
- updated_at         TIMESTAMPTZ    DEFAULT now()
Why: name split into first/last (regional uses one full_name field).

TABLE: flight
- flight_id            SERIAL         PK
- flight_number        VARCHAR(8)     NOT NULL      (e.g. DM104)
- origin_code          CHAR(3)        FK -> airport.airport_code
- destination_code     CHAR(3)        FK -> airport.airport_code
- scheduled_departure  TIMESTAMPTZ    NOT NULL
- scheduled_arrival    TIMESTAMPTZ    NOT NULL
- actual_departure     TIMESTAMPTZ                  (NULL until it departs)
- actual_arrival       TIMESTAMPTZ
- flight_status        VARCHAR(10)    (SCHEDULED, LANDED, DELAYED, CANCELLED, DIVERTED)
- aircraft_type        VARCHAR(20)
- base_fare            NUMERIC(10,3)  NOT NULL      (BHD, economy price)
- notes                TEXT                         (delay/disruption notes -> pgvector)
- crew_manifest_ref    VARCHAR(30)    (operational only – ETL drops, from Appendix I)
- gate_code            VARCHAR(5)     (operational only – ETL drops)
- review_count         INTEGER        DEFAULT 0     (Flow 4 – written by Member 3)
- avg_rating           NUMERIC(3,2)                 (Flow 4)
- photo_like_total     INTEGER        DEFAULT 0     (Flow 4)
- updated_at           TIMESTAMPTZ    DEFAULT now()
Why: two FKs to airport (from/to); actual times let us calculate delays.

TABLE: booking
- booking_id         SERIAL         PK
- booking_reference  CHAR(6)        UNIQUE NOT NULL  (e.g. K7XQ2M)
- passenger_id       INTEGER        FK -> passenger.passenger_id
- booking_date       TIMESTAMPTZ    DEFAULT now()
- booking_status     VARCHAR(10)    (CONFIRMED, COMPLETED, CANCELLED)
- booking_channel    VARCHAR(6)     (WEB, APP, AGENT)
- payment_method     VARCHAR(20)
- session_ip         INET           (operational only – ETL drops)
- agent_remarks      TEXT           (operational only – ETL drops)
- updated_at         TIMESTAMPTZ    DEFAULT now()
Why: one booking = one purchase by one passenger; can hold several tickets.

TABLE: ticket
- ticket_id           SERIAL         PK
- ticket_number       VARCHAR(14)    UNIQUE NOT NULL
- booking_id          INTEGER        FK -> booking.booking_id  (ON DELETE CASCADE)
- flight_id           INTEGER        FK -> flight.flight_id
- cabin_class_id      SMALLINT       FK -> cabin_class.cabin_class_id
- seat_number         VARCHAR(4)                    (e.g. 21C)
- fare_paid           NUMERIC(10,3)  NOT NULL       (price at time of sale)
- ticket_status       VARCHAR(8)     (ISSUED, USED, REFUNDED, VOID)
- baggage_tag_ref     VARCHAR(20)    (operational only – ETL drops)
- issued_terminal_id  VARCHAR(10)    (operational only – ETL drops)
- updated_at          TIMESTAMPTZ    DEFAULT now()
- UNIQUE (flight_id, seat_number)                   (no double-booked seats)
Why: links ONE booking to ONE flight (Appendix I). fare_paid is stored because
     the price paid must not change if the flight's base_fare changes later.


SCHEMA: regional_partner  (deliberately less normalised – 4 tables)

TABLE: traveler                                   (= passenger)
- traveler_code      VARCHAR(10)    PK            (text key, e.g. TRV-0001)
- full_name          VARCHAR(120)   NOT NULL      (one field, not first/last)
- email_address      VARCHAR(150)                 (NOT unique -> duplicates possible)
- birth_date_text    VARCHAR(20)                  (date stored as TEXT, mixed formats)
- country            VARCHAR(60)                  (free text: 'Bahrain', 'BAHRAIN', 'KSA')
- loyalty_tier       VARCHAR(10)                  (Blue, Silver, Gold)
- registered_on      DATE
- mobile_no          VARCHAR(20)    (operational only – ETL drops)
- sms_opt_in         CHAR(1)        (operational only – ETL drops)  ('Y'/'N')
- last_modified      TIMESTAMP      DEFAULT now()
Why: different key type (text), single name field, weak data typing.

TABLE: route                                      (= flight)
- route_id           INTEGER        PK  identity starting at 5001
- route_code         VARCHAR(10)    NOT NULL      (e.g. PX210)
- origin_city        VARCHAR(60)    NOT NULL      (city NAME, no airport table)
- destination_city   VARCHAR(60)    NOT NULL
- departure_date     DATE           NOT NULL
- departure_time     TIME           NOT NULL
- arrival_time       TIME           NOT NULL
- delay_minutes      INTEGER                      (instead of actual times)
- route_status       VARCHAR(15)                  (free text: 'operated', 'Cancelled')
- fare_amount        NUMERIC(9,3)   NOT NULL      (standard fare, BHD)
- aircraft_reg       VARCHAR(10)    (operational only – ETL drops)
- ops_remark         TEXT           (operational only – ETL drops)
- last_modified      TIMESTAMP      DEFAULT now()
Why: no airport lookup; date/time split; delay stored as minutes.

TABLE: reservation                                (= booking)
- reservation_no     BIGINT         PK            (e.g. 900000001)
- pnr                VARCHAR(8)     NOT NULL
- traveler_code      VARCHAR(10)    FK -> traveler.traveler_code
- travel_class       VARCHAR(20)                  (ONE text field, no cabin table)
- reserved_at        TIMESTAMP      DEFAULT now()
- reservation_status VARCHAR(15)    NOT NULL      (inconsistent casing)
- sales_channel      VARCHAR(20)
- checkin_kiosk_code VARCHAR(10)    (operational only – ETL drops, from Appendix I)
- agent_terminal     VARCHAR(10)    (operational only – ETL drops)
- last_modified      TIMESTAMP      DEFAULT now()
Why: class as free text means typos are possible -> ETL must map it.

TABLE: fare_line                                  (= ticket)
- fare_line_id       INTEGER        PK  identity
- reservation_no     BIGINT         FK -> reservation.reservation_no  (ON DELETE CASCADE)
- route_id           INTEGER        FK -> route.route_id
- fare_amount        NUMERIC(9,3)                 (COPIED from route.fare_amount = denormalised)
- tax_amount         NUMERIC(9,3)
- currency           VARCHAR(3)     NOT NULL      ('BHD', 'bhd', 'USD')
- seat_label         VARCHAR(4)
- line_status        VARCHAR(12)
- promo_code         VARCHAR(12)    (operational only – ETL drops)
- legacy_fare_basis  VARCHAR(10)    (operational only – ETL drops)
- last_modified      TIMESTAMP      DEFAULT now()
Why: fare copied from route -> if the route price changes, old lines keep
     the old price (update anomaly). ETL reconciles it against mainline ticket.fare_paid.