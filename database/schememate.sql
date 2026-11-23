-- Run this against the SchemeMate database after the core users, roles, and
-- schemes tables are set up.
CREATE TABLE IF NOT EXISTS saved_schemes (
    user_id INT NOT NULL,
    scheme_id INT NOT NULL,
    saved_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, scheme_id),
    INDEX idx_saved_schemes_scheme_id (scheme_id),
    CONSTRAINT fk_saved_schemes_user
        FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_saved_schemes_scheme
        FOREIGN KEY (scheme_id) REFERENCES schemes (scheme_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS category_profiles (
    profile_id INT NOT NULL AUTO_INCREMENT,
    user_id INT NOT NULL,
    category_slug VARCHAR(40) NOT NULL,
    age SMALLINT UNSIGNED NOT NULL,
    state VARCHAR(100) NOT NULL,
    district VARCHAR(100) NOT NULL,
    education_level VARCHAR(60) DEFAULT NULL,
    annual_income DECIMAL(14, 2) NOT NULL,
    social_category VARCHAR(40) DEFAULT NULL,
    profile_data LONGTEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id),
    INDEX idx_category_profiles_user_category (user_id, category_slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Link job-seeker profiles to the signed-in user so scheme matching can load
-- that user's latest profile. Existing rows remain unlinked.
SET @jobseeker_user_id_exists = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'jobseeker_profiles'
      AND column_name = 'user_id'
);
SET @jobseeker_user_id_sql = IF(
    @jobseeker_user_id_exists = 0,
    'ALTER TABLE jobseeker_profiles ADD COLUMN user_id INT NULL',
    'SELECT 1'
);
PREPARE jobseeker_user_id_stmt FROM @jobseeker_user_id_sql;
EXECUTE jobseeker_user_id_stmt;
DEALLOCATE PREPARE jobseeker_user_id_stmt;

SET @jobseeker_user_index_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'jobseeker_profiles'
      AND index_name = 'idx_jobseeker_profiles_user_id'
);
SET @jobseeker_user_index_sql = IF(
    @jobseeker_user_index_exists = 0,
    'CREATE INDEX idx_jobseeker_profiles_user_id ON jobseeker_profiles (user_id, id)',
    'SELECT 1'
);
PREPARE jobseeker_user_index_stmt FROM @jobseeker_user_index_sql;
EXECUTE jobseeker_user_index_stmt;
DEALLOCATE PREPARE jobseeker_user_index_stmt;

-- Indicative scheme records for matching. Verify full eligibility on the
-- linked official scheme portal before applying.
INSERT INTO schemes (
    scheme_name, description, target_role, state, min_age, max_age,
    max_income, category, education_level, benefit, documents,
    application_process, official_link
)
SELECT seed.scheme_name, seed.description, seed.target_role, seed.state,
       seed.min_age, seed.max_age, seed.max_income, seed.category,
       seed.education_level, seed.benefit, seed.documents,
       seed.application_process, seed.official_link
FROM (
    SELECT
        'Pradhan Mantri Matru Vandana Yojana (PMMVY)' AS scheme_name,
        'Maternity benefit for eligible pregnant and lactating women. Pregnancy and other scheme-specific conditions are not collected in this profile.' AS description,
        'Woman' AS target_role, 'All India' AS state, NULL AS min_age,
        NULL AS max_age, NULL AS max_income, 'All' AS category,
        'All' AS education_level,
        'Financial assistance for eligible beneficiaries under current scheme rules.' AS benefit,
        'Check the current scheme page for required identity, bank, and maternity documents.' AS documents,
        'Check current eligibility and apply through the official channel listed on myScheme.' AS application_process,
        'https://pmmvy.wcd.gov.in/' AS official_link
    UNION ALL SELECT
        'Pradhan Mantri Ujjwala Yojana (PMUY)',
        'LPG connection support for eligible adult women from households meeting scheme conditions. Household eligibility and existing LPG connection are not collected in this profile.',
        'Woman', 'All India', 18, NULL, NULL, 'All', 'All',
        'Support towards an LPG connection for eligible households.',
        'Check the current scheme page for identity, household, and eligibility documents.',
        'Check current eligibility and apply through the official channel listed on myScheme.',
        'https://pmuy.gov.in/'
    UNION ALL SELECT
        'Indira Gandhi National Old Age Pension Scheme (IGNOAPS)',
        'Pension support for eligible older persons. Age alone does not establish eligibility; household and state-specific conditions apply.',
        'Senior Citizen', 'All India', 60, NULL, NULL, 'All', 'All',
        'Monthly pension support as per current central and state rules.',
        'Check the current scheme page for age, household, identity, and residence documents.',
        'Check current eligibility and apply through the official channel listed on myScheme.',
        'https://www.myscheme.gov.in/find-scheme'
    UNION ALL SELECT
        'Atal Vayo Abhyuday Yojana (AVYAY)',
        'Government support initiatives for senior citizens. Specific services and eligibility depend on the component and implementing authority.',
        'Senior Citizen', 'All India', 60, NULL, NULL, 'All', 'All',
        'Access to support services and programmes for eligible senior citizens.',
        'Check the current scheme page for the relevant component and required documents.',
        'Check current eligibility and access details through myScheme.',
        'https://www.dosje.gov.in/'
    UNION ALL SELECT
        'Assistance to Disabled Persons for Purchase/Fitting of Aids and Appliances (ADIP)',
        'Assistive-device support for eligible persons with disabilities. Disability certification, income limits, and other conditions apply and are not fully assessed by this profile.',
        'Person with Disability', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Assistive devices for eligible beneficiaries under current scheme guidelines.',
        'Check the current scheme page for disability certificate, income, and assessment documents.',
        'Check current eligibility and apply through an authorized implementing agency listed on myScheme.',
        'https://depwd.gov.in/en/schemes/'
    UNION ALL SELECT
        'Divyangjan Swavalamban Yojana',
        'Concessional finance for eligible persons with disabilities for income-generating and other approved activities. Certification and lending conditions apply.',
        'Person with Disability', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Concessional financial assistance for approved activities.',
        'Check the current scheme page for disability, identity, project, and lender documents.',
        'Check current eligibility and participating-channel details on myScheme.',
        'https://ndfdc.nic.in/schemes'
    UNION ALL SELECT
        'Pradhan Mantri Employment Generation Programme (PMEGP)',
        'Credit-linked support for eligible new micro-enterprise projects. Age, project, location, and other programme conditions apply.',
        'Entrepreneur', 'All India', 18, NULL, NULL, 'All', 'All',
        'Margin-money subsidy and bank credit for eligible new projects under current rules.',
        'Check the current scheme page for project, identity, and qualification documents.',
        'Check eligibility and application steps through the official channel listed on myScheme.',
        'https://www.kviconline.gov.in/pmegpeportal/'
    UNION ALL SELECT
        'Pradhan Mantri Mudra Yojana (PMMY)',
        'Institutional credit for eligible micro-enterprise activities. Loan approval and terms depend on the lender and scheme rules.',
        'Entrepreneur', 'All India', 18, NULL, NULL, 'All', 'All',
        'Loans for eligible micro-enterprise activities through participating lenders.',
        'Check the current scheme page and lender for identity, business, and financial documents.',
        'Approach a participating lender after confirming current scheme details on myScheme.',
        'https://www.mudra.org.in/'
    UNION ALL SELECT
        'Pradhan Mantri Kaushal Vikas Yojana (PMKVY)',
        'Skill training and certification for eligible candidates in approved courses. Course, age, and batch conditions apply.',
        'Job Seeker', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Skill training and certification under approved programme components.',
        'Check the current scheme page and training provider for enrolment documents.',
        'Check current courses and enrolment channels through myScheme.',
        'https://www.skillindiadigital.gov.in/'
    UNION ALL SELECT
        'Deen Dayal Upadhyaya Grameen Kaushalya Yojana (DDU-GKY)',
        'Placement-linked skill training for eligible rural youth from poor households. Rural residence, poverty, age, and other conditions apply.',
        'Job Seeker', 'All India', 18, 35, NULL, 'All', 'All',
        'Skill training and placement support through approved projects.',
        'Check the current scheme page for residence, household, identity, and training documents.',
        'Check current eligibility and available training projects through myScheme.',
        'https://www.myscheme.gov.in/find-scheme'
    UNION ALL SELECT
        'Ayushman Bharat - Pradhan Mantri Jan Arogya Yojana (AB-PMJAY)',
        'Hospitalization cover for eligible families identified under applicable criteria. This profile does not assess the official beneficiary database or state-specific rules.',
        'Other', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Cashless hospital treatment cover for eligible families under current rules.',
        'Check beneficiary status and required documents on the current scheme page.',
        'Verify beneficiary status and access steps through myScheme or the official health-benefit channel.',
        'https://nha.gov.in/PM-JAY'
    UNION ALL SELECT
        'Pradhan Mantri Jan-Dhan Yojana (PMJDY)',
        'Financial inclusion through eligible bank accounts and related facilities. Account eligibility and benefits depend on current programme rules.',
        'Other', 'All India', 18, NULL, NULL, 'All', 'All',
        'Access to eligible basic banking services and linked facilities.',
        'Check the current scheme page and bank for identity and account-opening documents.',
        'Check current details on myScheme and contact a participating bank.',
        'https://pmjdy.gov.in/'
    UNION ALL SELECT
        'Post-Matric Scholarship for SC Students',
        'Scholarship support for eligible Scheduled Caste students pursuing post-matric or post-secondary studies. Income, course, and current application rules apply.',
        'Student', 'All India', NULL, NULL, 250000, 'SC', 'Post-Matric',
        'Scholarship assistance as per current central and state implementation guidelines.',
        'Check the National Scholarship Portal for current eligibility and required documents.',
        'Apply through the National Scholarship Portal when applications are open.',
        'https://scholarships.gov.in/'
    UNION ALL SELECT
        'Pradhan Mantri Krishi Sinchayee Yojana - Per Drop More Crop',
        'Micro-irrigation support to improve water-use efficiency. Availability, assistance, and application conditions are implemented by states.',
        'Farmer', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Support for eligible drip or sprinkler irrigation interventions under current guidelines.',
        'Check state agriculture department guidance and required land, identity, and bank documents.',
        'Apply through the state agriculture department or its designated portal.',
        'https://pmksy.gov.in/'
    UNION ALL SELECT
        'Pradhan Mantri Surakshit Matritva Abhiyan (PMSMA)',
        'Free antenatal care services for pregnant women in the second or third trimester at designated government health facilities. Pregnancy status and trimester are not collected in this profile.',
        'Woman', 'All India', NULL, NULL, NULL, 'All', 'All',
        'A minimum package of antenatal care at designated facilities on the ninth of each month.',
        'Contact a designated government health facility for the records needed for antenatal care.',
        'Visit a designated government health facility; check the official programme page for details.',
        'https://pmsma.mohfw.gov.in/'
    UNION ALL SELECT
        'National Programme for Health Care of the Elderly (NPHCE)',
        'Government health services for older people through public health facilities. Service availability is delivered through state health systems.',
        'Senior Citizen', 'All India', 60, NULL, NULL, 'All', 'All',
        'Preventive, promotive, and clinical geriatric care through participating public health facilities.',
        'Contact a participating public health facility for locally required records.',
        'Contact a PHC, CHC, district hospital, or other participating facility.',
        'https://nhm.gov.in/index1.php?lang=1&level=2&sublinkid=1046&lid=605'
    UNION ALL SELECT
        'Scholarship Scheme for Students with Disabilities',
        'Scholarship assistance for eligible students with disabilities. Enrollment, disability certification, income, and scheme-component conditions apply.',
        'Person with Disability', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Education assistance under the current scholarship component and guidelines.',
        'Check the Department of Empowerment of Persons with Disabilities for component-specific documents.',
        'Check current scholarship components and application instructions on the official department page.',
        'https://depwd.gov.in/en/schemes/'
    UNION ALL SELECT
        'Pradhan Mantri Formalisation of Micro Food Processing Enterprises Scheme (PMFME)',
        'Support for eligible micro food-processing enterprises, including formalisation and assistance under current scheme guidelines. Food-processing activity and other conditions apply.',
        'Entrepreneur', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Credit-linked and capacity-building support for eligible micro food-processing enterprises.',
        'Check the Ministry of Food Processing Industries portal for current project and applicant documents.',
        'Check current application guidance through the official PMFME portal.',
        'https://pmfme.mofpi.gov.in/'
    UNION ALL SELECT
        'National Apprenticeship Promotion Scheme (NAPS)',
        'Apprenticeship training opportunities under the Apprentices Act. Eligibility depends on the trade, employer, and current apprenticeship rules.',
        'Job Seeker', 'All India', NULL, NULL, NULL, 'All', 'All',
        'Apprenticeship training and related support under current programme rules.',
        'Check the apprenticeship portal for trade-specific age, education, and identity requirements.',
        'Register and search for apprenticeship opportunities through the official portal.',
        'https://www.apprenticeshipindia.gov.in/'
    UNION ALL SELECT
        'Pradhan Mantri Jeevan Jyoti Bima Yojana (PMJJBY)',
        'Renewable life-insurance cover for eligible bank or post-office account holders in the prescribed age group, subject to current scheme terms.',
        'Other', 'All India', 18, 50, NULL, 'All', 'All',
        'Life-insurance cover under current scheme terms and premium rates.',
        'Check the official scheme portal and participating bank or post office for enrollment documents.',
        'Enroll through a participating bank or post office after reviewing current terms.',
        'https://jansuraksha.gov.in/'
) AS seed
WHERE NOT EXISTS (
    SELECT 1
    FROM schemes existing
    WHERE existing.scheme_name = seed.scheme_name
      AND existing.target_role = seed.target_role
);

UPDATE schemes
SET official_link = CASE scheme_name
    WHEN 'Pradhan Mantri Matru Vandana Yojana (PMMVY)'
        THEN 'https://pmmvy.wcd.gov.in/'
    WHEN 'Pradhan Mantri Ujjwala Yojana (PMUY)'
        THEN 'https://pmuy.gov.in/'
    WHEN 'Atal Vayo Abhyuday Yojana (AVYAY)'
        THEN 'https://www.dosje.gov.in/'
    WHEN 'Assistance to Disabled Persons for Purchase/Fitting of Aids and Appliances (ADIP)'
        THEN 'https://depwd.gov.in/en/schemes/'
    WHEN 'Divyangjan Swavalamban Yojana'
        THEN 'https://ndfdc.nic.in/schemes'
    WHEN 'Pradhan Mantri Employment Generation Programme (PMEGP)'
        THEN 'https://www.kviconline.gov.in/pmegpeportal/'
    WHEN 'Pradhan Mantri Mudra Yojana (PMMY)'
        THEN 'https://www.mudra.org.in/'
    WHEN 'Pradhan Mantri Kaushal Vikas Yojana (PMKVY)'
        THEN 'https://www.skillindiadigital.gov.in/'
    WHEN 'Ayushman Bharat - Pradhan Mantri Jan Arogya Yojana (AB-PMJAY)'
        THEN 'https://nha.gov.in/PM-JAY'
    WHEN 'Pradhan Mantri Jan-Dhan Yojana (PMJDY)'
        THEN 'https://pmjdy.gov.in/'
    ELSE official_link
END
WHERE target_role IN (
    'Woman', 'Senior Citizen', 'Person with Disability',
    'Entrepreneur', 'Job Seeker', 'Other'
);