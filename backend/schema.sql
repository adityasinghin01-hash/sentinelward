-- SentinelWard backend schema (sw_api). Idempotent: safe to run on every start-up.
-- All times are epoch milliseconds UTC (bigint). Missing values are NULL, never 0.
-- Raw waveforms are never stored; vitals_1s keeps one row per bed per second.

-- Ward configuration (synced from ward.yaml at start-up) -------------------------------

CREATE TABLE IF NOT EXISTS beds (
    bed_id      text PRIMARY KEY,
    device_id   text NOT NULL UNIQUE,
    nurse       text,
    ts          bigint NOT NULL              -- when this row was last synced from ward.yaml
);
CREATE INDEX IF NOT EXISTS beds_bed_ts ON beds (bed_id, ts);
CREATE INDEX IF NOT EXISTS beds_device_ts ON beds (device_id, ts);

CREATE TABLE IF NOT EXISTS patients (
    bed_id      text PRIMARY KEY REFERENCES beds (bed_id),
    initials    text NOT NULL,
    age         integer,
    sex         text,
    ts          bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS patients_bed_ts ON patients (bed_id, ts);

-- Hub data ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vitals_1s (
    bed_id          text NOT NULL,
    ts              bigint NOT NULL,         -- vitals.ts from the monitor
    device_id       text NOT NULL,
    seq             bigint,
    hr              double precision,
    spo2            double precision,
    rr              double precision,
    sys             double precision,        -- only in the second a new cuff reading arrived
    dia             double precision,
    map             double precision,
    nibp_ts         bigint,
    abp_mean        double precision,        -- mean of the 125 ABP samples, NULL without an arterial line
    alarm_code      text,
    alarm_priority  text,
    verdict         text,                    -- verdict in force when the second arrived
    trusted         boolean NOT NULL,        -- set to false later if a verdict moves last_trusted_ts back
    received_ts     bigint NOT NULL          -- server clock when the message arrived
);
CREATE INDEX IF NOT EXISTS vitals_1s_bed_ts ON vitals_1s (bed_id, ts);

CREATE TABLE IF NOT EXISTS scores (
    bed_id          text NOT NULL,
    ts              bigint NOT NULL,         -- score.window_start
    model           text NOT NULL,
    model_version   text NOT NULL,
    window_s        integer NOT NULL,
    score           double precision NOT NULL,
    label           text NOT NULL,
    reason          text NOT NULL,
    extra           jsonb NOT NULL,
    received_ts     bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS scores_bed_ts ON scores (bed_id, ts);

CREATE TABLE IF NOT EXISTS verdicts (
    bed_id          text NOT NULL,
    ts              bigint NOT NULL,
    window_start    bigint NOT NULL,
    verdict         text NOT NULL,
    priority        text NOT NULL,
    confidence      double precision NOT NULL,
    trust           double precision NOT NULL,
    last_trusted_ts bigint,
    msg             jsonb NOT NULL           -- the full verdict message, unchanged
);
CREATE INDEX IF NOT EXISTS verdicts_bed_ts ON verdicts (bed_id, ts);

CREATE TABLE IF NOT EXISTS actions (
    action_id       text PRIMARY KEY,
    ts              bigint NOT NULL,
    actor           text NOT NULL,           -- action.by (A1..A9 or staff:<name>)
    action          text NOT NULL,
    bed_id          text,
    device_id       text,
    detail          text NOT NULL,
    undo_id         text,
    undoes          text,
    approved_by     text,
    result          text NOT NULL,
    msg             jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS actions_bed_ts ON actions (bed_id, ts);
CREATE INDEX IF NOT EXISTS actions_device_ts ON actions (device_id, ts);
CREATE INDEX IF NOT EXISTS actions_ts ON actions (ts);

-- Latest state of each alert (one row per alert_id) ...
CREATE TABLE IF NOT EXISTS alerts (
    alert_id        text PRIMARY KEY,
    ts              bigint NOT NULL,
    bed_id          text NOT NULL,
    verdict         text NOT NULL,
    priority        text NOT NULL,
    status          text NOT NULL,
    ladder_step     integer NOT NULL,
    acked_by        text,
    acked_ts        bigint,
    msg             jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_bed_ts ON alerts (bed_id, ts);
CREATE INDEX IF NOT EXISTS alerts_status_ts ON alerts (status, ts);

-- ... and every version that arrived.
CREATE TABLE IF NOT EXISTS alert_history (
    alert_id        text NOT NULL,
    ts              bigint NOT NULL,
    bed_id          text NOT NULL,
    status          text NOT NULL,
    ladder_step     integer NOT NULL,
    msg             jsonb NOT NULL,
    received_ts     bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS alert_history_bed_ts ON alert_history (bed_id, ts);
CREATE INDEX IF NOT EXISTS alert_history_alert_ts ON alert_history (alert_id, ts);

CREATE TABLE IF NOT EXISTS bedside_checks (
    bed_id          text NOT NULL,
    ts              bigint NOT NULL,
    result          text NOT NULL,
    actor           text NOT NULL
);
CREATE INDEX IF NOT EXISTS bedside_checks_bed_ts ON bedside_checks (bed_id, ts);

CREATE TABLE IF NOT EXISTS manual_readings (
    reading_id      text PRIMARY KEY,
    bed_id          text NOT NULL,
    ts              bigint NOT NULL,
    actor           text NOT NULL,
    hr              double precision,
    spo2            double precision,
    sys             double precision,
    dia             double precision,
    rr              double precision
);
CREATE INDEX IF NOT EXISTS manual_readings_bed_ts ON manual_readings (bed_id, ts);

-- All fields of every net_features message are kept in data; the common ones are columns.
CREATE TABLE IF NOT EXISTS net_features (
    device_id       text NOT NULL,
    ts              bigint NOT NULL,         -- net_features.window_start
    window_s        integer NOT NULL,
    data            jsonb NOT NULL,          -- the full message, including fields added later
    received_ts     bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS net_features_device_ts ON net_features (device_id, ts);

-- Records from agents (ward/record) and from staff ------------------------------------

CREATE TABLE IF NOT EXISTS records (
    record_id       text PRIMARY KEY,
    kind            text NOT NULL,           -- ticket, report, incident, briefing, workload
    ts              bigint NOT NULL,         -- record.ts of the version kept
    actor           text NOT NULL,           -- record.by
    version         integer NOT NULL,        -- +1 on every replacement or staff edit
    data            jsonb NOT NULL,
    bed_id          text,                    -- copied from data.bed_id when it is a string
    device_id       text,                    -- copied from data.device_id when it is a string
    updated_ts      bigint,                  -- last staff edit
    updated_by      text
);
CREATE INDEX IF NOT EXISTS records_bed_ts ON records (bed_id, ts);
CREATE INDEX IF NOT EXISTS records_device_ts ON records (device_id, ts);
CREATE INDEX IF NOT EXISTS records_kind_ts ON records (kind, ts);

CREATE TABLE IF NOT EXISTS record_audit (
    record_id       text NOT NULL,
    ts              bigint NOT NULL,
    actor           text NOT NULL,           -- staff:<name>
    field           text NOT NULL,           -- top-level key of data
    old_value       jsonb,                   -- NULL when the field did not exist
    new_value       jsonb,
    bed_id          text
);
CREATE INDEX IF NOT EXISTS record_audit_bed_ts ON record_audit (bed_id, ts);
CREATE INDEX IF NOT EXISTS record_audit_record_ts ON record_audit (record_id, ts);

-- Screen buttons ------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS requests (
    request_id      text PRIMARY KEY,
    ts              bigint NOT NULL,
    actor           text NOT NULL,
    action          text NOT NULL,
    target_id       text NOT NULL,
    bed_id          text,
    note            text NOT NULL,
    msg             jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS requests_bed_ts ON requests (bed_id, ts);
CREATE INDEX IF NOT EXISTS requests_ts ON requests (ts);

CREATE TABLE IF NOT EXISTS nurse_calls (
    call_id         text PRIMARY KEY,
    bed_id          text NOT NULL,
    ts              bigint NOT NULL,
    actor           text NOT NULL,
    note            text NOT NULL,
    urgency         text NOT NULL,           -- routine or urgent
    status          text NOT NULL,           -- open, or replaced by a newer call
    closed_ts       bigint,
    closed_by       text
);
CREATE INDEX IF NOT EXISTS nurse_calls_bed_ts ON nurse_calls (bed_id, ts);

CREATE TABLE IF NOT EXISTS assignments (
    bed_id          text NOT NULL,
    ts              bigint NOT NULL,
    nurse           text NOT NULL,           -- staff:<name>
    status          text NOT NULL,           -- assigned, on_my_way, reviewing, complete
    actor           text NOT NULL
);
CREATE INDEX IF NOT EXISTS assignments_bed_ts ON assignments (bed_id, ts);

-- Demo runs (kept by /api/demo/reset) ---------------------------------------------------

CREATE TABLE IF NOT EXISTS demo_runs (
    run_id          text NOT NULL,
    cmd             text NOT NULL,           -- run or reset
    ts              bigint NOT NULL,
    start_at_s      integer NOT NULL,
    scenario        text,
    speed           double precision,
    actor           text,                    -- NULL when the command came from another publisher
    PRIMARY KEY (run_id, cmd)
);
CREATE INDEX IF NOT EXISTS demo_runs_ts ON demo_runs (ts);

-- Upgrades (idempotent) -----------------------------------------------------------------
-- Retry-safe uniqueness: a batch that is written twice (after a failed commit) changes nothing.

ALTER TABLE vitals_1s ADD COLUMN IF NOT EXISTS second bigint;          -- ts / 1000, one row per bed per second
CREATE UNIQUE INDEX IF NOT EXISTS vitals_1s_bed_second ON vitals_1s (bed_id, second);
ALTER TABLE scores ALTER COLUMN score DROP NOT NULL;                    -- missing score = NULL (model not eligible)
CREATE UNIQUE INDEX IF NOT EXISTS scores_bed_model_ts ON scores (bed_id, model, ts);
CREATE UNIQUE INDEX IF NOT EXISTS verdicts_bed_ts_unique ON verdicts (bed_id, ts);
CREATE UNIQUE INDEX IF NOT EXISTS alert_history_unique ON alert_history (alert_id, ts, status, ladder_step);
CREATE UNIQUE INDEX IF NOT EXISTS bedside_checks_unique ON bedside_checks (bed_id, ts, actor, result);
CREATE UNIQUE INDEX IF NOT EXISTS net_features_device_ts_unique ON net_features (device_id, ts);
ALTER TABLE net_features ADD COLUMN IF NOT EXISTS msgs_per_s double precision;
ALTER TABLE net_features ADD COLUMN IF NOT EXISTS bytes_per_s double precision;
ALTER TABLE net_features ADD COLUMN IF NOT EXISTS malformed double precision;
ALTER TABLE net_features ADD COLUMN IF NOT EXISTS seq_gaps double precision;
ALTER TABLE net_features ADD COLUMN IF NOT EXISTS seq_repeats double precision;
ALTER TABLE net_features ADD COLUMN IF NOT EXISTS stale_ms double precision;
ALTER TABLE manual_readings ADD COLUMN IF NOT EXISTS notes text NOT NULL DEFAULT '';
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS clinician_id text;     -- as sent by the screen
ALTER TABLE assignments ALTER COLUMN nurse DROP NOT NULL;               -- staff ID when the clinician is a configured user
ALTER TABLE record_audit ADD COLUMN IF NOT EXISTS seq bigserial;        -- keeps audit order within one millisecond
CREATE INDEX IF NOT EXISTS demo_runs_run_ts ON demo_runs (run_id, ts);

-- Publications not yet accepted by the hub survive a restart and are retried in order.
CREATE TABLE IF NOT EXISTS outbox (
    publication_id  text PRIMARY KEY,
    seq             bigserial,
    ts              bigint NOT NULL,
    msg             jsonb NOT NULL,
    sent_ts         bigint
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox (seq) WHERE sent_ts IS NULL;
