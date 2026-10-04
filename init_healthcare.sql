-- Healthcare Analytics Database Setup

-- 1. Create Raw Source Tables
CREATE TABLE IF NOT EXISTS raw_patients (
    patient_id SERIAL PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(10) NOT NULL,
    blood_type VARCHAR(5) NOT NULL,
    city VARCHAR(50) NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_doctors (
    doctor_id SERIAL PRIMARY KEY,
    doctor_name VARCHAR(100) NOT NULL,
    specialty VARCHAR(50) NOT NULL,
    department VARCHAR(50) NOT NULL,
    hospital_branch VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_appointments (
    appointment_id SERIAL PRIMARY KEY,
    patient_id INT NOT NULL REFERENCES raw_patients(patient_id),
    doctor_id INT NOT NULL REFERENCES raw_doctors(doctor_id),
    appointment_date TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED',
    consultation_fee NUMERIC(10, 2) NOT NULL DEFAULT 150.00
);

CREATE TABLE IF NOT EXISTS raw_lab_tests (
    test_id SERIAL PRIMARY KEY,
    appointment_id INT NOT NULL REFERENCES raw_appointments(appointment_id),
    test_name VARCHAR(100) NOT NULL,
    test_cost NUMERIC(10, 2) NOT NULL,
    test_result VARCHAR(50) NOT NULL,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Populate Sample Data
INSERT INTO raw_patients (full_name, date_of_birth, gender, blood_type, city) VALUES
('Siddharth Rao', '1985-04-12', 'Male', 'O+', 'Hyderabad'),
('Meera Nambiar', '1992-09-25', 'Female', 'A+', 'Bengaluru'),
('Arjun Mehta', '1978-11-03', 'Male', 'B+', 'Mumbai'),
('Kavita Krishnan', '1999-01-18', 'Female', 'AB+', 'Chennai'),
('Rajesh Gupta', '1965-07-30', 'Male', 'O-', 'Delhi');

INSERT INTO raw_doctors (doctor_name, specialty, department, hospital_branch) VALUES
('Dr. Ramesh Varma', 'Cardiology', 'Cardiovascular Sciences', 'Apollo Jubilee Hills'),
('Dr. Sunita Deshmukh', 'Neurology', 'Neurosciences', 'Apollo Banjara Hills'),
('Dr. Anil Kapoor', 'Orthopedics', 'Surgical Specialties', 'Apollo Jubilee Hills'),
('Dr. Shweta Menon', 'General Medicine', 'Internal Medicine', 'Apollo Secunderabad');

INSERT INTO raw_appointments (patient_id, doctor_id, appointment_date, status, consultation_fee) VALUES
(1, 1, '2026-09-10 10:00:00', 'COMPLETED', 200.00),
(2, 2, '2026-09-11 11:30:00', 'COMPLETED', 250.00),
(3, 3, '2026-09-12 14:00:00', 'COMPLETED', 180.00),
(4, 4, '2026-09-13 09:15:00', 'COMPLETED', 150.00),
(5, 1, '2026-09-14 16:30:00', 'COMPLETED', 200.00),
(1, 4, '2026-09-18 10:30:00', 'COMPLETED', 150.00),
(2, 1, '2026-09-20 15:00:00', 'COMPLETED', 200.00);

INSERT INTO raw_lab_tests (appointment_id, test_name, test_cost, test_result) VALUES
(1, 'Lipid Profile', 65.00, 'NORMAL'),
(1, 'Electrocardiogram (ECG)', 120.00, 'NORMAL'),
(2, 'Brain MRI', 450.00, 'CLEAR'),
(3, 'Knee X-Ray', 85.00, 'MILD_ARTHRITIS'),
(5, 'Cardiac Stress Test (TMT)', 150.00, 'BORDERLINE'),
(6, 'Complete Blood Count (CBC)', 40.00, 'NORMAL'),
(7, 'Echocardiogram', 200.00, 'NORMAL');

-- 3. Staging Views
CREATE OR REPLACE VIEW stg_patients AS
SELECT
    patient_id,
    full_name,
    DATE_PART('year', AGE(CURRENT_DATE, date_of_birth))::INT AS age_years,
    gender,
    blood_type,
    city
FROM raw_patients;

CREATE OR REPLACE VIEW stg_appointments AS
SELECT
    a.appointment_id,
    a.patient_id,
    a.doctor_id,
    d.doctor_name,
    d.specialty,
    d.hospital_branch,
    a.appointment_date,
    a.status,
    a.consultation_fee
FROM raw_appointments a
JOIN raw_doctors d ON a.doctor_id = d.doctor_id;

-- 4. Analytical Mart Views
CREATE OR REPLACE VIEW fct_patient_encounters AS
SELECT
    a.appointment_id AS encounter_id,
    p.patient_id,
    p.full_name AS patient_name,
    p.age_years,
    p.gender,
    a.doctor_id,
    a.doctor_name,
    a.specialty,
    a.hospital_branch,
    a.appointment_date,
    a.status AS encounter_status,
    a.consultation_fee
FROM stg_appointments a
JOIN stg_patients p ON a.patient_id = p.patient_id;

CREATE OR REPLACE VIEW patient_billing_summary AS
SELECT
    e.patient_id,
    e.patient_name,
    COUNT(DISTINCT e.encounter_id) AS total_visits,
    COALESCE(SUM(e.consultation_fee), 0.00) AS total_consultation_fees,
    COALESCE(SUM(t.test_cost), 0.00) AS total_lab_fees,
    COALESCE(SUM(e.consultation_fee), 0.00) + COALESCE(SUM(t.test_cost), 0.00) AS grand_total_billed
FROM fct_patient_encounters e
LEFT JOIN raw_lab_tests t ON e.encounter_id = t.appointment_id
GROUP BY e.patient_id, e.patient_name;

CREATE OR REPLACE VIEW doctor_revenue_summary AS
SELECT
    doctor_id,
    doctor_name,
    specialty,
    COUNT(encounter_id) AS total_appointments,
    COUNT(CASE WHEN encounter_status = 'COMPLETED' THEN 1 END) AS completed_appointments,
    COALESCE(SUM(consultation_fee), 0.00) AS total_consultation_revenue
FROM fct_patient_encounters
GROUP BY doctor_id, doctor_name, specialty;
