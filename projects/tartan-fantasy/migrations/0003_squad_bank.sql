-- NULL identifies legacy squads whose bank is reconstructed from price reviews.
ALTER TABLE squads ADD COLUMN bank REAL;
