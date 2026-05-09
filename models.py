from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from database import Base

_ts = dict(default=datetime.utcnow)
_ts_update = dict(default=datetime.utcnow, onupdate=datetime.utcnow)
_deleted = dict(default=False)


class Phone(Base):
    __tablename__ = "phones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(Text)
    title = Column(Text)
    extension = Column(Text)
    model = Column(Text)
    serial = Column(Text, unique=True)
    mac_eth0 = Column(Text)
    mac_wlan = Column(Text, nullable=True)
    factory_password = Column(Text)
    display_name = Column(Text)
    created_at = Column(DateTime, **_ts)
    updated_at = Column(DateTime, **_ts_update)
    deleted = Column(Boolean, **_deleted)

    config = relationship("PhoneConfig", back_populates="phone", uselist=False, cascade="all, delete-orphan")
    vpk_keys = relationship("VpkKey", back_populates="phone", cascade="all, delete-orphan", order_by="VpkKey.slot")
    sip_accounts = relationship("SipAccount", back_populates="phone", cascade="all, delete-orphan", order_by="SipAccount.account_num")
    wifi_ssids = relationship("WifiSsid", back_populates="phone", cascade="all, delete-orphan", order_by="WifiSsid.ssid_num")

    @property
    def subscriber_name(self) -> str:
        for acct in self.sip_accounts:
            if acct.account_num == 1:
                return acct.subscriber_name or ""
        return ""


class SipAccount(Base):
    __tablename__ = "sip_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_id = Column(Integer, ForeignKey("phones.id"), nullable=False)
    account_num = Column(Integer)
    enabled = Column(Boolean, default=False)
    display_name = Column(Text, default="")
    subscriber_name = Column(Text, default="")
    password = Column(Text, default="")
    extension = Column(Text, default="")
    sip_server_1 = Column(Text, default="192.168.1.1")
    sip_server_2 = Column(Text, default="pbx.example.com")
    sip_server_1_port = Column(Integer, default=5060)
    sip_server_2_port = Column(Integer, default=5060)
    voicemail_number = Column(Text, default="*97")
    created_at = Column(DateTime, **_ts)
    updated_at = Column(DateTime, **_ts_update)
    deleted = Column(Boolean, **_deleted)

    phone = relationship("Phone", back_populates="sip_accounts")


class WifiSsid(Base):
    __tablename__ = "wifi_ssids"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_id = Column(Integer, ForeignKey("phones.id"), nullable=False)
    ssid_num = Column(Integer)
    enabled = Column(Boolean, default=False)
    essid = Column(Text, default="")
    psk = Column(Text, default="")
    key_mgmt = Column(Text, default="WPA_PSK")
    hidden = Column(Boolean, default=False)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, **_ts)
    updated_at = Column(DateTime, **_ts_update)
    deleted = Column(Boolean, **_deleted)

    phone = relationship("Phone", back_populates="wifi_ssids")


class PhoneConfig(Base):
    __tablename__ = "phone_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_id = Column(Integer, ForeignKey("phones.id"), nullable=False)
    phonebook_server = Column(Text, default="192.168.1.1")
    phonebook_mode = Column(Text, default="EnabledUseTFTP")
    phonebook_interval = Column(Integer, default=720)
    phonebook_protocol = Column(Text, default="TFTP")
    phonebook_sortby = Column(Text, default="FirstName")
    phonebook_keyfunction = Column(Text, default="LocalPhonebook")
    phonebook_defaultsearchmode = Column(Text, default="QuickMatch")
    wifi_enabled = Column(Boolean, default=True)
    wifi_band = Column(Text, default="Auto")
    wifi_country_code = Column(Text, default="US")
    wallpaper_source = Column(Text, default="ColorBackground")
    screensaver_enabled = Column(Boolean, default=False)
    sip_notify_challenge = Column(Boolean, default=True)
    vpn_enabled = Column(Boolean, default=False)
    vpn_server = Column(Text, default="")
    vpn_port = Column(Integer, default=1194)
    vpn_transport = Column(Text, default="udp")
    vpn_cipher = Column(Text, default="AES256GCM")
    vpn_ca = Column(Text, default="")
    vpn_cert = Column(Text, default="")
    vpn_client_key = Column(Text, default="")
    datetime_date_format = Column(Text, default="yyyy-mm-dd")
    datetime_time_format = Column(Text, default="24Hour")
    datetime_show_on_statusbar = Column(Text, default="fullDate")
    created_at = Column(DateTime, **_ts)
    updated_at = Column(DateTime, **_ts_update)
    deleted = Column(Boolean, **_deleted)

    phone = relationship("Phone", back_populates="config")


class VpkKey(Base):
    __tablename__ = "vpk_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_id = Column(Integer, ForeignKey("phones.id"), nullable=False)
    slot = Column(Integer)
    keymode = Column(Text, default="None")
    description = Column(Text, default="")
    value = Column(Text, default="")
    account = Column(Text, default="Account1")
    created_at = Column(DateTime, **_ts)
    updated_at = Column(DateTime, **_ts_update)
    deleted = Column(Boolean, **_deleted)

    phone = relationship("Phone", back_populates="vpk_keys")


class PhonebookEntry(Base):
    __tablename__ = "phonebook_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(Text, nullable=False, default="")
    phone_number = Column(Text, nullable=False, default="")
    account_index = Column(Integer, default=1)
    frequent = Column(Integer, default=0)
    created_at = Column(DateTime, **_ts)
    updated_at = Column(DateTime, **_ts_update)
    deleted = Column(Boolean, **_deleted)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(Text, primary_key=True)
    value = Column(Text)
    created_at = Column(DateTime, **_ts)
    updated_at = Column(DateTime, **_ts_update)
    deleted = Column(Boolean, **_deleted)
