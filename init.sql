-- init.sql

CREATE DATABASE carbon_data;

-- Create the generation table
CREATE TABLE IF NOT EXISTS generation (
    id SERIAL PRIMARY KEY,
    fuel VARCHAR(50),
    perc NUMERIC(5, 2),
    from_time TIMESTAMPTZ,
    to_time TIMESTAMPTZ
);

-- Create the intensity table
CREATE TABLE IF NOT EXISTS intensity (
    id SERIAL PRIMARY KEY,
    from_time TIMESTAMPTZ,
    to_time TIMESTAMPTZ,
    intensity_forecast INTEGER,
    intensity_actual INTEGER,
    intensity_index VARCHAR(20)
);