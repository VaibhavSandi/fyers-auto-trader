-- Live mode now places a real broker-side SL-M stop order as a backstop
-- alongside the existing software-managed stop (see order_manager.py). This
-- column tracks that order's broker_order_id so it can be found and
-- cancelled again on the matching exit, or recovered after a restart.

ALTER TABLE positions ADD COLUMN protective_stop_order_id TEXT;
