-- EHMS migration 0013: public hotel website managed from EHMS (content with draft and published versions, images,
-- and enquiries sent from the website's contact form).

CREATE TABLE website_content (
  id {PK},
  hotel_id {REF} NOT NULL UNIQUE REFERENCES hotels(id),
  draft TEXT NOT NULL,
  published TEXT,
  updated_by {REF} REFERENCES users(id),
  updated_at {TS} NOT NULL,
  published_by {REF} REFERENCES users(id),
  published_at {TS}
);

CREATE TABLE website_media (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  filename VARCHAR(200) NOT NULL,
  content_type VARCHAR(50) NOT NULL,
  caption VARCHAR(150),
  size_bytes INTEGER NOT NULL,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_website_media ON website_media(hotel_id);

CREATE TABLE website_enquiries (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  kind VARCHAR(10) NOT NULL CHECK (kind IN ('general','rooms','dining','event')),
  name VARCHAR(150) NOT NULL,
  email VARCHAR(200) NOT NULL,
  phone VARCHAR(50),
  subject VARCHAR(200),
  message TEXT NOT NULL,
  event_date {DATE},
  guests INTEGER,
  marketing_consent INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(10) NOT NULL DEFAULT 'new' CHECK (status IN ('new','replied','closed','spam')),
  note VARCHAR(500),
  handled_by {REF} REFERENCES users(id),
  handled_at {TS},
  ip VARCHAR(64),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_website_enquiries ON website_enquiries(hotel_id, status);
