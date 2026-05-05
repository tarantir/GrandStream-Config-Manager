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


def _add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    if column not in _col_names(conn, table):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def _drop_column_if_exists(conn, table: str, column: str) -> None:
    if column in _col_names(conn, table):
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


def init_db():
    import models  # noqa: F401 — ensures models are registered before create_all
    Base.metadata.create_all(bind=engine)

    # ── Add columns that were added after initial schema ──────────────────────
    with engine.connect() as conn:
        _add_column_if_missing(conn, "phone_configs", "screensaver_enabled",            "BOOLEAN DEFAULT 0")
        _add_column_if_missing(conn, "phone_configs", "screensaver_source",              "TEXT DEFAULT 'Default'")
        _add_column_if_missing(conn, "phone_configs", "screensaver_timeout",             "INTEGER DEFAULT 3")
        _add_column_if_missing(conn, "phone_configs", "screensaver_showdatetime",        "BOOLEAN DEFAULT 1")
        _add_column_if_missing(conn, "phone_configs", "screensaver_serverpath",          "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "phone_configs", "screensaver_downloadxmlinterval", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "phone_configs", "screensaver_useprogrammablekeys", "BOOLEAN DEFAULT 0")
        _add_column_if_missing(conn, "sip_accounts",  "subscriber_name",                  "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "phone_configs", "sip_notify_challenge",             "BOOLEAN DEFAULT 1")
        _add_column_if_missing(conn, "phone_configs", "datetime_date_format",            "TEXT DEFAULT 'yyyy-mm-dd'")
        _add_column_if_missing(conn, "phone_configs", "datetime_time_format",            "TEXT DEFAULT '24Hour'")
        _add_column_if_missing(conn, "phone_configs", "datetime_show_on_statusbar",      "TEXT DEFAULT 'fullDate'")

        for table in ("phones", "sip_accounts", "wifi_ssids", "phone_configs",
                      "vpk_keys", "phonebook_entries", "app_settings"):
            _add_column_if_missing(conn, table, "created_at", "DATETIME")
            _add_column_if_missing(conn, table, "updated_at", "DATETIME")
            _add_column_if_missing(conn, table, "deleted",    "BOOLEAN DEFAULT 0")

        conn.commit()

    # ── Seed wifi_ssids from legacy phone_configs columns ─────────────────────
    db = SessionLocal()
    try:
        from models import Phone, WifiSsid
        for phone in db.query(Phone).filter(~Phone.wifi_ssids.any()).all():
            row = db.execute(
                text("SELECT wifi_ssid, wifi_psk, wifi_key_mgmt FROM phone_configs WHERE phone_id = :pid"),
                {"pid": phone.id}
            ).fetchone()
            db.add(WifiSsid(
                phone_id=phone.id, ssid_num=1, enabled=True,
                essid=row[0] if row and row[0] else "",
                psk=row[1] if row and row[1] else "",
                key_mgmt=row[2] if row and row[2] else "WPA_PSK",
            ))
            for n in range(2, 5):
                db.add(WifiSsid(phone_id=phone.id, ssid_num=n, enabled=False))
        db.commit()
    finally:
        db.close()

    # ── Seed sip_accounts from legacy phone_configs SIP columns ───────────────
    db = SessionLocal()
    try:
        from models import Phone, SipAccount
        for phone in db.query(Phone).filter(~Phone.sip_accounts.any()).all():
            row = db.execute(
                text("SELECT sip_server_1, sip_server_2, voicemail_number "
                     "FROM phone_configs WHERE phone_id = :pid"),
                {"pid": phone.id}
            ).fetchone()
            db.add(SipAccount(
                phone_id=phone.id, account_num=1, enabled=True,
                display_name=phone.display_name or phone.extension or "",
                extension=phone.extension or "",
                sip_server_1=row[0] if row and row[0] else "192.168.1.1",
                sip_server_2=row[1] if row and row[1] else "pbx.example.com",
                voicemail_number=row[2] if row and row[2] else "*97",
            ))
            for n in range(2, 7):
                db.add(SipAccount(phone_id=phone.id, account_num=n, enabled=False,
                                  display_name="", extension=""))
        db.commit()
    finally:
        db.close()

    # ── Drop legacy columns (data already migrated above) ─────────────────────
    with engine.connect() as conn:
        for col in ("sip_server_1", "sip_server_2", "sip_server_1_port", "sip_server_2_port",
                    "sip_transport", "register_expiration", "voicemail_number",
                    "wifi_ssid", "wifi_psk", "wifi_key_mgmt"):
            _drop_column_if_exists(conn, "phone_configs", col)
        for col in ("sip_transport", "register_expiration"):
            _drop_column_if_exists(conn, "sip_accounts", col)
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
