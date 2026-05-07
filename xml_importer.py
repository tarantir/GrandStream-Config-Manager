import xml.etree.ElementTree as ET
from datetime import datetime
from sqlalchemy.orm import Session
from models import Phone, PhoneConfig, SipAccount, VpkKey, WifiSsid


def _parts(item: ET.Element) -> dict[str, str]:
    return {p.get("name", ""): (p.text or "") for p in item.findall("part")}


def _load_xml(content: bytes) -> ET.Element:
    # Strip UTF-8 BOM (\xef\xbb\xbf) — some editors and GS tools prepend it
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    content = content.strip()
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        # ET rejects an encoding="..." declaration on a unicode string, so
        # decode, strip the declaration, and retry.
        text = content.decode("utf-8", errors="replace")
        if text.startswith("<?xml"):
            text = text[text.index("?>") + 2:].lstrip()
        return ET.fromstring(text)


def parse_xml(content: bytes) -> dict:
    """
    Returns:
      accounts: {1: {display_name, extension, sip_server_1, ...}, ...}
      vpk_keys: [{slot, keymode, description, value, account}, ...]
      + phone-level keys: hotdesking_*, wifi_*, phonebook_*, wallpaper_*, screensaver_*
    """
    root = _load_xml(content)
    config_el = root.find("config")
    if config_el is None:
        raise ValueError("No <config> element found")

    result: dict = {}
    accounts: dict[int, dict] = {}
    wifi_ssids: dict[int, dict] = {}
    vpk_keys: list[dict] = []

    def _acct(n: int) -> dict:
        if n not in accounts:
            accounts[n] = {}
        return accounts[n]

    def _ssid(n: int) -> dict:
        if n not in wifi_ssids:
            wifi_ssids[n] = {}
        return wifi_ssids[n]

    for item in config_el.findall("item"):
        name = item.get("name", "")
        parts = _parts(item)

        # ── Account identity: account.N ───────────────────────────────────────
        import re
        m = re.fullmatch(r"account\.(\d+)", name)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 6:
                if "name" in parts:
                    _acct(n)["display_name"] = parts["name"]
                if "enable" in parts:
                    _acct(n)["enabled"] = parts["enable"].lower() == "yes"
            continue

        # ── SIP settings: account.N.sip ───────────────────────────────────────
        m = re.fullmatch(r"account\.(\d+)\.sip", name)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 6 and "userid" in parts:
                _acct(n)["extension"] = parts["userid"]
            continue

        # ── SIP subscriber: account.N.sip.subscriber ─────────────────────────
        m = re.fullmatch(r"account\.(\d+)\.sip\.subscriber", name)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 6:
                if "name" in parts:
                    _acct(n)["subscriber_name"] = parts["name"]
                if "password" in parts:
                    _acct(n)["password"] = parts["password"]
            continue

        # ── Voicemail: account.N.sip.voicemail ───────────────────────────────
        m = re.fullmatch(r"account\.(\d+)\.sip\.voicemail", name)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 6 and "number" in parts:
                _acct(n)["voicemail_number"] = parts["number"]
            continue

        # ── SIP server 1: account.N.sip.server.1 ─────────────────────────────
        m = re.fullmatch(r"account\.(\d+)\.sip\.server\.1", name)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 6 and "address" in parts:
                _acct(n)["sip_server_1"] = parts["address"]
            continue

        # ── SIP server 2: account.N.sip.server.2 ─────────────────────────────
        m = re.fullmatch(r"account\.(\d+)\.sip\.server\.2", name)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 6 and "address" in parts:
                _acct(n)["sip_server_2"] = parts["address"]
            continue

        # ── OpenVPN ───────────────────────────────────────────────────────────
        if name == "network.openvpn":
            result["vpn_enabled"] = parts.get("enable", "").lower() == "yes"
            if "server" in parts:
                result["vpn_server"] = parts["server"]
            if "port" in parts:
                try:
                    result["vpn_port"] = int(parts["port"])
                except (ValueError, TypeError):
                    pass
            if "transport" in parts:
                result["vpn_transport"] = parts["transport"]
            if "cipermethod" in parts:
                result["vpn_cipher"] = parts["cipermethod"]
            if "ca" in parts:
                result["vpn_ca"] = parts["ca"]
            if "cert" in parts:
                result["vpn_cert"] = parts["cert"]
            if "clientKey" in parts:
                result["vpn_client_key"] = parts["clientKey"]

        # ── SIP notify ────────────────────────────────────────────────────────
        elif name == "sip.notify":
            if "challenge" in parts:
                result["sip_notify_challenge"] = parts["challenge"].lower() == "yes"

        # ── Hotdesking ────────────────────────────────────────────────────────
        elif name == "hotdesking.server":
            if "path" in parts:
                result["hotdesking_server"] = parts["path"]
            if "type" in parts:
                result["hotdesking_type"] = parts["type"]

        # ── WiFi (phone-level) ────────────────────────────────────────────────
        elif name == "network.wifi":
            result["wifi_enabled"] = parts.get("enable", "").lower() == "on"
            if "band" in parts:
                result["wifi_band"] = parts["band"]

        # ── WiFi SSIDs ────────────────────────────────────────────────────────
        elif name.startswith("network.wifi.ssid."):
            m = re.fullmatch(r"network\.wifi\.ssid\.(\d+)", name)
            if m:
                n = int(m.group(1))
                if 1 <= n <= 4:
                    if "essid" in parts:
                        _ssid(n)["essid"] = parts["essid"]
                    if "psk" in parts:
                        _ssid(n)["psk"] = parts["psk"]
                    if "key_management" in parts:
                        _ssid(n)["key_mgmt"] = parts["key_management"]
                    if "enabled" in parts:
                        _ssid(n)["enabled"] = parts["enabled"].lower() == "yes"
                    if "hidden" in parts:
                        _ssid(n)["hidden"] = parts["hidden"].lower() == "yes"
                    if "priority" in parts:
                        try:
                            _ssid(n)["priority"] = int(parts["priority"])
                        except ValueError:
                            pass

        # ── VPK keys ──────────────────────────────────────────────────────────
        elif name.startswith("pks.vpk."):
            try:
                slot = int(name.split(".")[-1])
            except ValueError:
                continue
            vpk_keys.append({
                "slot": slot,
                "keymode": parts.get("keymode", "None"),
                "description": parts.get("description", ""),
                "value": parts.get("value", ""),
                "account": parts.get("account", "Account1"),
            })

        # ── Phonebook ─────────────────────────────────────────────────────────
        elif name == "phonebook.download":
            if "server" in parts:
                result["phonebook_server"] = parts["server"]
            if "mode" in parts:
                result["phonebook_mode"] = parts["mode"]
            if "interval" in parts:
                try:
                    result["phonebook_interval"] = int(parts["interval"])
                except ValueError:
                    pass

        # ── Date/time format ─────────────────────────────────────────────────
        elif name == "datetime.format":
            if "date" in parts:
                result["datetime_date_format"] = parts["date"]
            if "time" in parts:
                result["datetime_time_format"] = parts["time"]

        # ── Date/time display ─────────────────────────────────────────────────
        elif name == "datetime":
            if "showonstatusbar" in parts:
                result["datetime_show_on_statusbar"] = parts["showonstatusbar"]
        # ── Wallpaper ─────────────────────────────────────────────────────────
        elif name == "lcd.wallpaper":
            if "color" in parts:
                result["wallpaper_color"] = parts["color"]
            if "source" in parts:
                result["wallpaper_source"] = parts["source"]

        # ── Screensaver ───────────────────────────────────────────────────────
        elif name == "lcd.screensaver":
            if "enable" in parts:
                result["screensaver_enabled"] = parts["enable"].lower() == "yes"
            if "source" in parts:
                result["screensaver_source"] = parts["source"]
            if "timeout" in parts:
                try:
                    result["screensaver_timeout"] = int(parts["timeout"])
                except ValueError:
                    pass
            if "showdatetime" in parts:
                result["screensaver_showdatetime"] = parts["showdatetime"].lower() == "yes"
            if "serverpath" in parts:
                result["screensaver_serverpath"] = parts["serverpath"]
            if "downloadxmlinterval" in parts:
                try:
                    result["screensaver_downloadxmlinterval"] = int(parts["downloadxmlinterval"])
                except ValueError:
                    pass
            if "useprogrammablekeys" in parts:
                result["screensaver_useprogrammablekeys"] = parts["useprogrammablekeys"].lower() == "yes"

    result["accounts"] = accounts
    result["wifi_ssids"] = wifi_ssids
    result["vpk_keys"] = vpk_keys
    return result


PHONE_CONFIG_FIELDS = [
    "phonebook_server", "phonebook_mode", "phonebook_interval", "phonebook_protocol",
    "hotdesking_server", "hotdesking_type",
    "wifi_enabled", "wifi_band",
    "wallpaper_color", "wallpaper_source",
    "screensaver_enabled", "screensaver_source", "screensaver_timeout",
    "screensaver_showdatetime", "screensaver_serverpath",
    "screensaver_downloadxmlinterval", "screensaver_useprogrammablekeys",
    "sip_notify_challenge",
    "vpn_enabled", "vpn_server", "vpn_port", "vpn_transport",
    "vpn_cipher", "vpn_ca", "vpn_cert", "vpn_client_key",
    "datetime_date_format", "datetime_time_format",
    "datetime_show_on_statusbar",
]

WIFI_SSID_FIELDS = ["essid", "psk", "key_mgmt", "enabled", "hidden", "priority"]

ACCOUNT_FIELDS = [
    "display_name", "subscriber_name", "password", "extension", "enabled",
    "sip_server_1", "sip_server_2", "sip_server_3",
    "voicemail_number",
]


def apply_parsed(phone: Phone, parsed: dict, db: Session) -> None:
    phone.updated_at = datetime.utcnow()

    # Phone-level config
    cfg = phone.config
    if cfg is None:
        cfg = PhoneConfig(phone_id=phone.id)
        db.add(cfg)
        db.flush()

    for field in PHONE_CONFIG_FIELDS:
        if field in parsed:
            if field == "wifi_enabled" and phone.model == "GRP2613":
                continue
            setattr(cfg, field, parsed[field])

    # WiFi SSIDs
    incoming_ssids = parsed.get("wifi_ssids", {})
    existing_ssids = {s.ssid_num: s for s in phone.wifi_ssids}
    for n, data in incoming_ssids.items():
        if not (1 <= n <= 4):
            continue
        s = existing_ssids.get(n)
        if s is None:
            s = WifiSsid(phone_id=phone.id, ssid_num=n)
            db.add(s)
        for field in WIFI_SSID_FIELDS:
            if field in data:
                setattr(s, field, data[field])

    # SIP accounts
    incoming_accounts = parsed.get("accounts", {})
    existing_accounts = {a.account_num: a for a in phone.sip_accounts}

    for n, data in incoming_accounts.items():
        if not (1 <= n <= 6):
            continue
        acct = existing_accounts.get(n)
        if acct is None:
            acct = SipAccount(phone_id=phone.id, account_num=n)
            db.add(acct)
        for field in ACCOUNT_FIELDS:
            if field in data:
                setattr(acct, field, data[field])

    # Sync Phone.display_name from account 1 subscriber_name if present
    if 1 in incoming_accounts and "subscriber_name" in incoming_accounts[1]:
        phone.display_name = incoming_accounts[1]["subscriber_name"]

    # VPK keys
    if parsed.get("vpk_keys"):
        max_slots = 6 if phone.model == "GRP2613" else 4
        existing = {v.slot: v for v in phone.vpk_keys}
        incoming = {v["slot"]: v for v in parsed["vpk_keys"]}

        for slot in range(1, max_slots + 1):
            if slot in incoming:
                data = incoming[slot]
                if slot in existing:
                    vpk = existing[slot]
                    vpk.keymode = data["keymode"]
                    vpk.description = data["description"]
                    vpk.value = data["value"]
                    vpk.account = data["account"]
                else:
                    db.add(VpkKey(
                        phone_id=phone.id, slot=slot,
                        keymode=data["keymode"], description=data["description"],
                        value=data["value"], account=data["account"],
                    ))
            elif slot not in existing:
                db.add(VpkKey(
                    phone_id=phone.id, slot=slot,
                    keymode="None", description="", value="", account="Account1",
                ))

    db.commit()


def import_xml_for_phone(content: bytes, phone: Phone, db: Session) -> dict:
    parsed = parse_xml(content)
    apply_parsed(phone, parsed, db)
    accounts_updated = list(parsed.get("accounts", {}).keys())
    return {
        "extension": phone.extension,
        "accounts_updated": accounts_updated,
        "vpk_slots_updated": len(parsed.get("vpk_keys", [])),
    }


def import_xml_bulk(files: list[tuple[str, bytes]], db: Session) -> dict:
    imported = []
    errors = []

    for filename, content in files:
        stem = filename.rsplit(".", 1)[0]
        phone = db.query(Phone).filter(Phone.extension == stem).first()
        if phone is None:
            errors.append(f"{filename}: no phone with extension '{stem}' found")
            continue
        try:
            result = import_xml_for_phone(content, phone, db)
            imported.append(result)
        except Exception as e:
            errors.append(f"{filename}: {e}")

    return {"imported": imported, "errors": errors}
