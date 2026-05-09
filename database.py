import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "sqlite:///./phones.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _col_names(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _table_names(conn) -> set[str]:
    return {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    if column not in _col_names(conn, table):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def _drop_column_if_exists(conn, table: str, column: str) -> None:
    if column in _col_names(conn, table):
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


def _rename_column_if_exists(conn, table: str, old_col: str, new_col: str) -> None:
    """Rename a column. Requires SQLite ≥ 3.25.0 (2018-09-15)."""
    cols = _col_names(conn, table)
    if old_col in cols and new_col not in cols:
        conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}"))


def init_db():
    import models  # noqa: F401 — ensures models are registered before create_all

    # ── Rename legacy tables BEFORE create_all so SQLAlchemy sees new names ──
    with engine.connect() as conn:
        tables = _table_names(conn)
        if "phones" in tables and "endpoints" not in tables:
            conn.execute(text("ALTER TABLE phones RENAME TO endpoints"))
        if "phone_configs" in tables and "endpoint_config" not in tables:
            conn.execute(text("ALTER TABLE phone_configs RENAME TO endpoint_config"))
        conn.commit()

    Base.metadata.create_all(bind=engine)

    # ── Add columns that were added after initial schema ──────────────────────
    with engine.connect() as conn:
        _add_column_if_missing(conn, "endpoint_config", "screensaver_enabled",            "BOOLEAN DEFAULT 0")
        _add_column_if_missing(conn, "sip_accounts",    "subscriber_name",                "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "sip_accounts",    "password",                       "TEXT DEFAULT ''")

        _add_column_if_missing(conn, "endpoint_config", "phonebook_sortby",               "TEXT DEFAULT 'FirstName'")
        _add_column_if_missing(conn, "endpoint_config", "phonebook_keyfunction",          "TEXT DEFAULT 'LocalPhonebook'")
        _add_column_if_missing(conn, "endpoint_config", "phonebook_defaultsearchmode",    "TEXT DEFAULT 'QuickMatch'")
        _add_column_if_missing(conn, "endpoint_config", "sip_notify_challenge",           "BOOLEAN DEFAULT 1")
        _add_column_if_missing(conn, "endpoint_config", "vpn_enabled",                   "BOOLEAN DEFAULT 0")
        _add_column_if_missing(conn, "endpoint_config", "vpn_server",                    "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "endpoint_config", "vpn_port",                      "INTEGER DEFAULT 1194")
        _add_column_if_missing(conn, "endpoint_config", "vpn_transport",                 "TEXT DEFAULT 'udp'")
        _add_column_if_missing(conn, "endpoint_config", "vpn_cipher",                    "TEXT DEFAULT 'AES256GCM'")
        _add_column_if_missing(conn, "endpoint_config", "vpn_ca",                        "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "endpoint_config", "vpn_cert",                      "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "endpoint_config", "vpn_client_key",                "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "endpoint_config", "datetime_date_format",          "TEXT DEFAULT 'yyyy-mm-dd'")
        _add_column_if_missing(conn, "endpoint_config", "datetime_time_format",          "TEXT DEFAULT '24Hour'")
        _add_column_if_missing(conn, "endpoint_config", "datetime_show_on_statusbar",    "TEXT DEFAULT 'fullDate'")
        _add_column_if_missing(conn, "endpoint_config", "wifi_country_code",             "TEXT DEFAULT 'US'")
        _add_column_if_missing(conn, "endpoint_config", "webaccess_timeout",             "INTEGER DEFAULT 60")
        _add_column_if_missing(conn, "endpoint_config", "webaccess_authtimeout",         "INTEGER DEFAULT 60")
        _add_column_if_missing(conn, "endpoint_config", "webaccess_accesstimeout",       "INTEGER DEFAULT 60")
        _add_column_if_missing(conn, "endpoint_config", "idle_sc_softkey_mode",          "TEXT DEFAULT 'Default'")
        _add_column_if_missing(conn, "endpoint_config", "idle_softkey_layout_enable",    "TEXT DEFAULT 'Yes'")
        _add_column_if_missing(conn, "endpoint_config", "idle_layout_state",             "TEXT DEFAULT 'Next,Custom1,History,ForwardAll,Redial'")
        _add_column_if_missing(conn, "endpoint_config", "dialing_softkeys_enable",       "TEXT DEFAULT 'Yes'")
        _add_column_if_missing(conn, "endpoint_config", "dialing_layout_state",          "TEXT DEFAULT 'Custom1,EndCall,ReConf,ConfRoom,Redial,Dial,Backspace'")
        _add_column_if_missing(conn, "endpoint_config", "dialing_softkey_mode",          "TEXT DEFAULT 'Default'")

        for table in ("endpoints", "sip_accounts", "wifi_ssids", "endpoint_config",
                      "vpk_keys", "phonebook_entries", "app_settings"):
            _add_column_if_missing(conn, table, "created_at", "DATETIME")
            _add_column_if_missing(conn, table, "updated_at", "DATETIME")
            _add_column_if_missing(conn, table, "deleted",    "BOOLEAN DEFAULT 0")

        conn.commit()

    # ── Rename phone_id → endpoint_id in all child tables ─────────────────────
    with engine.connect() as conn:
        for table in ("sip_accounts", "wifi_ssids", "endpoint_config", "vpk_keys"):
            _rename_column_if_exists(conn, table, "phone_id", "endpoint_id")
        conn.commit()

    # ── Rename group_name → account in endpoints ──────────────────────────────
    with engine.connect() as conn:
        _rename_column_if_exists(conn, "endpoints", "group_name", "account")
        conn.commit()

    # ── Seed wifi_ssids from legacy endpoint_config columns ───────────────────
    db = SessionLocal()
    try:
        from models import Phone, WifiSsid
        for phone in db.query(Phone).filter(~Phone.wifi_ssids.any()).all():
            row = db.execute(
                text("SELECT wifi_ssid, wifi_psk, wifi_key_mgmt FROM endpoint_config WHERE endpoint_id = :pid"),
                {"pid": phone.id}
            ).fetchone()
            db.add(WifiSsid(
                endpoint_id=phone.id, ssid_num=0, enabled=True,
                essid=row[0] if row and row[0] else "",
                psk=row[1] if row and row[1] else "",
                key_mgmt=row[2] if row and row[2] else "WPA_PSK",
            ))
            for n in range(1, 4):
                db.add(WifiSsid(endpoint_id=phone.id, ssid_num=n, enabled=False))
        db.commit()
    finally:
        db.close()

    # ── Seed sip_accounts from legacy endpoint_config SIP columns ─────────────
    db = SessionLocal()
    try:
        from models import Phone, SipAccount
        for phone in db.query(Phone).filter(~Phone.sip_accounts.any()).all():
            row = db.execute(
                text("SELECT sip_server_1, sip_server_2, voicemail_number "
                     "FROM endpoint_config WHERE endpoint_id = :pid"),
                {"pid": phone.id}
            ).fetchone()
            db.add(SipAccount(
                endpoint_id=phone.id, account_num=1, enabled=True,
                display_name=phone.display_name or phone.extension or "",
                extension=phone.extension or "",
                sip_server_1=row[0] if row and row[0] else "192.168.1.1",
                sip_server_2=row[1] if row and row[1] else "pbx.example.com",
                voicemail_number=row[2] if row and row[2] else "*97",
            ))
            for n in range(2, 5):
                db.add(SipAccount(endpoint_id=phone.id, account_num=n, enabled=False,
                                  display_name="", extension=""))
        db.commit()
    finally:
        db.close()

    # ── Drop legacy columns (data already migrated above) ─────────────────────
    with engine.connect() as conn:
        for col in ("sip_server_1", "sip_server_2", "sip_server_1_port", "sip_server_2_port",
                    "sip_transport", "register_expiration", "voicemail_number",
                    "wifi_ssid", "wifi_psk", "wifi_key_mgmt"):
            _drop_column_if_exists(conn, "endpoint_config", col)
        for col in ("sip_transport", "register_expiration"):
            _drop_column_if_exists(conn, "sip_accounts", col)
        conn.commit()

    # ── Drop stale columns identified in Tier 1 schema audit ─────────────────
    with engine.connect() as conn:
        # Host Desking remnants — feature removed, columns never referenced in code
        _drop_column_if_exists(conn, "endpoint_config", "hotdesking_server")
        _drop_column_if_exists(conn, "endpoint_config", "hotdesking_type")
        # Wallpaper redesign remnant — wallpaper_source retained; wallpaper_color orphaned
        _drop_column_if_exists(conn, "endpoint_config", "wallpaper_color")
        # Screensaver extended config — only screensaver_enabled was kept in the redesign
        for col in ("screensaver_source", "screensaver_timeout", "screensaver_showdatetime",
                    "screensaver_serverpath", "screensaver_downloadxmlinterval",
                    "screensaver_useprogrammablekeys"):
            _drop_column_if_exists(conn, "endpoint_config", col)
        # VPN mode — intentionally excluded from XML output; always default '0'
        _drop_column_if_exists(conn, "endpoint_config", "vpn_mode")
        # SIP server 3 — no UI, no generator output, no importer path
        _drop_column_if_exists(conn, "sip_accounts", "sip_server_3")
        # SIP server port columns — port is part of the address string (host:port); never read
        _drop_column_if_exists(conn, "sip_accounts", "sip_server_1_port")
        _drop_column_if_exists(conn, "sip_accounts", "sip_server_2_port")
        # WiFi SSID priority — no UI, no generator output, all rows null/zero
        _drop_column_if_exists(conn, "wifi_ssids", "priority")
        # endpoints.title — written as "{ext} {model}", never read anywhere
        _drop_column_if_exists(conn, "endpoints", "title")
        conn.commit()

    # ── Ensure FK indexes exist ───────────────────────────────────────────────
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sip_accounts_endpoint_id "
            "ON sip_accounts(endpoint_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_wifi_ssids_endpoint_id "
            "ON wifi_ssids(endpoint_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_vpk_keys_endpoint_id "
            "ON vpk_keys(endpoint_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_endpoint_config_endpoint_id "
            "ON endpoint_config(endpoint_id)"
        ))
        conn.commit()

    # ── Seed app settings ─────────────────────────────────────────────────────
    db = SessionLocal()
    try:
        from models import AppSetting
        if db.query(AppSetting).count() == 0:
            db.add_all([
                AppSetting(key="output_dir",               value="./output"),
                AppSetting(key="default_sip_server_1",     value="192.168.1.1"),
                AppSetting(key="default_sip_server_2",     value="pbx.example.com"),
                AppSetting(key="default_phonebook_server", value="192.168.1.1"),
            ])
            db.commit()
        os.makedirs("./output", exist_ok=True)
    finally:
        db.close()
