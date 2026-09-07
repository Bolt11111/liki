-- Corrects 004's initial conservation rule for installations which applied it before release accounting existed.
ALTER TABLE risk_reservations ADD COLUMN released_amount numeric NOT NULL DEFAULT 0 CHECK(released_amount >= 0);
ALTER TABLE risk_reservations DROP CONSTRAINT risk_reservations_check;
ALTER TABLE risk_reservations ADD CONSTRAINT risk_reservations_conservation
  CHECK(working_amount + position_amount + released_amount = original_amount);
