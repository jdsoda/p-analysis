-- ITR Client-wise PL/BS + Projection system
CREATE TABLE IF NOT EXISTS clients (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  client_name VARCHAR(255) NOT NULL,
  proprietor_name VARCHAR(255) NULL,
  address TEXT NULL,
  pan VARCHAR(20) NULL,
  contact VARCHAR(30) NULL,
  business_type VARCHAR(120) NULL,
  notes TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_client_name (client_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS financial_years (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  client_id INT UNSIGNED NOT NULL,
  financial_year VARCHAR(9) NOT NULL,
  status ENUM('draft','actual','projected','estimated','completed') NOT NULL DEFAULT 'draft',
  source_pdf_name VARCHAR(255) NULL,
  source_pdf_path VARCHAR(500) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_client_fy (client_id, financial_year),
  CONSTRAINT fk_fy_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS account_values (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  financial_year_id INT UNSIGNED NOT NULL,
  statement_type ENUM('TRADING','P&L','BALANCE_SHEET') NOT NULL,
  field_key VARCHAR(120) NOT NULL,
  field_label VARCHAR(255) NOT NULL,
  amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  source_type ENUM('PDF','EXCEL','MANUAL','CALCULATED','CARRY_FORWARD') NOT NULL DEFAULT 'MANUAL',
  growth_method ENUM('AUTO_GROWTH','MANUAL','CARRY_FORWARD','FORMULA','ZERO','CUSTOM') NOT NULL DEFAULT 'MANUAL',
  growth_percent DECIMAL(8,2) NULL,
  source_value DECIMAL(18,2) NULL,
  sort_order INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fy_field (financial_year_id, statement_type, field_key),
  KEY idx_fy_statement (financial_year_id, statement_type),
  CONSTRAINT fk_av_fy FOREIGN KEY (financial_year_id) REFERENCES financial_years(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS field_mappings (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  variant_text VARCHAR(255) NOT NULL,
  standard_field VARCHAR(120) NOT NULL,
  statement_type ENUM('TRADING','P&L','BALANCE_SHEET') NOT NULL,
  confidence DECIMAL(5,2) NOT NULL DEFAULT 100,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_mapping (variant_text, standard_field, statement_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS projection_settings (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  client_id INT UNSIGNED NULL,
  field_key VARCHAR(120) NOT NULL,
  growth_percent DECIMAL(8,2) NOT NULL DEFAULT 10,
  growth_method ENUM('AUTO_GROWTH','MANUAL','CARRY_FORWARD','FORMULA','ZERO','CUSTOM') NOT NULL DEFAULT 'AUTO_GROWTH',
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_projection_setting (client_id, field_key),
  CONSTRAINT fk_ps_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  client_id INT UNSIGNED NULL,
  financial_year_id INT UNSIGNED NULL,
  action VARCHAR(80) NOT NULL,
  details TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_al_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL,
  CONSTRAINT fk_al_fy FOREIGN KEY (financial_year_id) REFERENCES financial_years(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
