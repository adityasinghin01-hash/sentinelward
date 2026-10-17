# Acceptance check 2026-10-17T17:26:48Z

| Check | Result | Detail |
|---|---|---|
| services | PASS | 6 units active |
| health | PASS | {"status": null, "mqtt_connected": true, "db_ok": true, "storage": "postgresql"} |
| flow | PASS | 9 beds: vitals + 6 scores + verdict every 5 s |
| contract | PASS | every observed message passed sw_common.validate |
| blank | PASS | 12 beds, none blank |
| hub-auth | PASS | anonymous connect reason=Not authorized |
| containers | PASS | 6 containers running |
