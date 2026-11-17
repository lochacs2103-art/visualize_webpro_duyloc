"""Schema SQLite. Tạo đủ bảng ngay từ Phase 1 để các phase sau không phải migrate."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  original_path TEXT,
  csv_path TEXT NOT NULL,
  parquet_path TEXT,
  date_folder TEXT NOT NULL,
  row_count INTEGER,
  col_count INTEGER,
  schema_json TEXT,
  uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(csv_path)
);

CREATE TABLE IF NOT EXISTS saved_views (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  filter_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS column_prefs (
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  column_name TEXT,
  visible INTEGER DEFAULT 1,
  pin_position INTEGER DEFAULT 0,
  width INTEGER,
  show_colors INTEGER DEFAULT 0,
  PRIMARY KEY (file_id, column_name)
);

CREATE TABLE IF NOT EXISTS saved_charts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  config_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS saved_pivots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  config_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS column_profiles (
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  column_name TEXT,
  profile_json TEXT NOT NULL,
  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (file_id, column_name)
);

CREATE TABLE IF NOT EXISTS format_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  column_name TEXT,
  operator TEXT,
  value TEXT,
  color TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_date ON files(date_folder);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
  file_id UNINDEXED,
  content,
  tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS raw_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  size_bytes INTEGER,
  sheet_names_json TEXT,
  uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mapping_projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mapping_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES mapping_projects(id) ON DELETE CASCADE,
  raw_file_id INTEGER REFERENCES raw_files(id) ON DELETE CASCADE,
  sheet_name TEXT NOT NULL,
  header_row INTEGER DEFAULT 1,
  is_active INTEGER DEFAULT 1,
  UNIQUE(project_id, raw_file_id, sheet_name)
);

CREATE TABLE IF NOT EXISTS mapping_target_columns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES mapping_projects(id) ON DELETE CASCADE,
  column_name TEXT NOT NULL,
  data_type TEXT NOT NULL,
  position INTEGER NOT NULL,
  UNIQUE(project_id, column_name)
);

CREATE TABLE IF NOT EXISTS mapping_column_map (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mapping_file_id INTEGER REFERENCES mapping_files(id) ON DELETE CASCADE,
  target_column_id INTEGER REFERENCES mapping_target_columns(id) ON DELETE CASCADE,
  source_column_name TEXT NOT NULL,
  transform_json TEXT,
  UNIQUE(mapping_file_id, target_column_id)
);

CREATE TABLE IF NOT EXISTS mapping_outputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER REFERENCES mapping_projects(id) ON DELETE CASCADE,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  row_count INTEGER,
  error_count INTEGER DEFAULT 0
);
"""
