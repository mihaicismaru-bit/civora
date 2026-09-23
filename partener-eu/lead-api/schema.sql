CREATE TABLE IF NOT EXISTS rpm_leads (
  lead_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  company TEXT NOT NULL,
  contact_name TEXT NOT NULL,
  contact TEXT NOT NULL,
  employees INTEGER NOT NULL,
  delivery_format TEXT NOT NULL,
  source_url TEXT,
  referrer TEXT,
  utm_source TEXT,
  utm_medium TEXT,
  utm_campaign TEXT,
  utm_content TEXT,
  status TEXT NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW','CONTACTED','QUALIFIED','WON','LOST')),
  notes TEXT,
  ip_hash TEXT,
  user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_rpm_leads_created_at ON rpm_leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rpm_leads_status ON rpm_leads(status);
CREATE INDEX IF NOT EXISTS idx_rpm_leads_campaign ON rpm_leads(utm_campaign);
