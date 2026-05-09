import os
from datetime import datetime
import xml.etree.ElementTree as ET
from models import Phone, PhoneConfig, VpkKey


def _sub(parent: ET.Element, tag: str, text: str = "") -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text:
        el.text = text
    return el


def _part(item: ET.Element, name: str, text: str = "") -> ET.Element:
    part = ET.SubElement(item, "part")
    part.set("name", name)
    if text:
        part.text = text
    return part


def _emit_account(config: ET.Element, n: int, acct) -> None:
    display = acct.display_name or acct.extension or ""
    ext = acct.extension or ""

    acc = ET.SubElement(config, "item")
    acc.set("name", f"account.{n}")
    _part(acc, "name", display)
    _part(acc, "enable", "Yes")

    sip = ET.SubElement(config, "item")
    sip.set("name", f"account.{n}.sip")
    _part(sip, "userid", ext)

    sub = ET.SubElement(config, "item")
    sub.set("name", f"account.{n}.sip.subscriber")
    _part(sub, "name", acct.subscriber_name or display)
    _part(sub, "userid", ext)
    _part(sub, "password", acct.password or "")

    vm = ET.SubElement(config, "item")
    vm.set("name", f"account.{n}.sip.voicemail")
    _part(vm, "number", acct.voicemail_number or "*97")

    srv1 = ET.SubElement(config, "item")
    srv1.set("name", f"account.{n}.sip.server.1")
    _part(srv1, "address", acct.sip_server_1 or "")

    srv2 = ET.SubElement(config, "item")
    srv2.set("name", f"account.{n}.sip.server.2")
    _part(srv2, "address", acct.sip_server_2 or "")



_KEY_MGMT_NUM = {"OPEN": "0", "WEP": "1", "WPA_EAP": "2", "WPA2_EAP": "3", "WPA_PSK": "4", "WPA2_PSK": "4"}


def generate_xml(phone: Phone) -> str:
    cfg: PhoneConfig = phone.config

    root = ET.Element("gs_provision")
    config = ET.SubElement(root, "config")
    config.set("version", "2")

    # SIP accounts (emit only enabled ones)
    acct_map = {a.account_num: a for a in phone.sip_accounts}
    for n in range(1, 5):
        acct = acct_map.get(n)
        if acct and acct.enabled:
            _emit_account(config, n, acct)

    # WiFi — skip for GRP2613 or if disabled
    if phone.model != "GRP2613" and cfg.wifi_enabled:
        cc = ET.SubElement(config, "item")
        cc.set("name", "network.wifi.countryCode")
        _part(cc, "public", cfg.wifi_country_code or "US")

        wifi = ET.SubElement(config, "item")
        wifi.set("name", "network.wifi")
        _part(wifi, "enable", "1")

        ssid_map = {s.ssid_num: s for s in phone.wifi_ssids}
        for n in range(0, 4):
            s = ssid_map.get(n)
            if not s or not s.essid:
                continue
            ssid = ET.SubElement(config, "item")
            ssid.set("name", f"network.wifi.ssid.{n}")
            _part(ssid, "eap_method", "0")
            _part(ssid, "essid", s.essid)
            _part(ssid, "hidden", "1" if s.hidden else "0")
            _part(ssid, "key_management", _KEY_MGMT_NUM.get(s.key_mgmt or "WPA_PSK", "4"))
            _part(ssid, "psk", s.psk or "")

    # VPN
    if cfg.vpn_enabled:
        vpn = ET.SubElement(config, "item")
        vpn.set("name", "network.openvpn")
        _part(vpn, "enable", "Yes")
        _part(vpn, "mode", "0")
        _part(vpn, "server", cfg.vpn_server or "")
        _part(vpn, "port", str(cfg.vpn_port or 1194))
        _part(vpn, "transport", cfg.vpn_transport or "udp")
        _part(vpn, "cipermethod", cfg.vpn_cipher or "AES256GCM")
        _part(vpn, "ca", cfg.vpn_ca or "")
        _part(vpn, "cert", cfg.vpn_cert or "")
        _part(vpn, "clientKey", cfg.vpn_client_key or "")

    # VPK keys — emit only non-None slots
    for vpk in sorted(phone.vpk_keys, key=lambda k: k.slot):
        if vpk.keymode == "None":
            continue
        item = ET.SubElement(config, "item")
        item.set("name", f"pks.vpk.{vpk.slot}")
        _part(item, "lockmode", "No")
        _part(item, "description", vpk.description or "")
        if vpk.keymode != "Line":
            _part(item, "value", vpk.value or "")
        _part(item, "keymode", vpk.keymode)
        _part(item, "account", vpk.account or "Account1")

    # SIP notify challenge
    notify = ET.SubElement(config, "item")
    notify.set("name", "sip.notify")
    _part(notify, "challenge", "Yes" if cfg.sip_notify_challenge else "No")

    # Phonebook
    pb = ET.SubElement(config, "item")
    pb.set("name", "phonebook.download")
    _part(pb, "interval", str(cfg.phonebook_interval or 720))
    _part(pb, "mode", cfg.phonebook_mode or "EnabledUseTFTP")
    _part(pb, "server", cfg.phonebook_server or "")

    pbs = ET.SubElement(config, "item")
    pbs.set("name", "phonebook")
    _part(pbs, "defaultsearchmode", cfg.phonebook_defaultsearchmode or "QuickMatch")
    _part(pbs, "keyfunction", cfg.phonebook_keyfunction or "LocalPhonebook")
    _part(pbs, "sortby", cfg.phonebook_sortby or "FirstName")

    # Date/time
    dtfmt = ET.SubElement(config, "item")
    dtfmt.set("name", "datetime.format")
    _part(dtfmt, "date", cfg.datetime_date_format or "yyyy-mm-dd")
    _part(dtfmt, "time", cfg.datetime_time_format or "24Hour")

    dt = ET.SubElement(config, "item")
    dt.set("name", "datetime")
    _part(dt, "showonstatusbar", cfg.datetime_show_on_statusbar or "fullDate")

    # Wallpaper
    wp = ET.SubElement(config, "item")
    wp.set("name", "lcd.wallpaper")
    _part(wp, "source", cfg.wallpaper_source or "ColorBackground")

    # Screensaver
    ss = ET.SubElement(config, "item")
    ss.set("name", "lcd.screensaver")
    _part(ss, "enable", "Yes" if cfg.screensaver_enabled else "No")

    ET.indent(root, space="    ")
    declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return declaration + ET.tostring(root, encoding="unicode")


def _timestamped_archive_dir(output_dir: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archive_dir = os.path.join(output_dir, "archive", timestamp)
    os.makedirs(archive_dir, exist_ok=True)
    return archive_dir


def write_xml(phone: Phone, output_dir: str) -> list[tuple[str, str]]:
    xml_content = generate_xml(phone)
    os.makedirs(output_dir, exist_ok=True)
    archive_dir = _timestamped_archive_dir(output_dir)
    files = []

    def _write(name: str, directory: str) -> tuple[str, str]:
        filepath = os.path.abspath(os.path.join(directory, name))
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(xml_content)
        return name, filepath

    # Generate file for SIP ID (extension)
    if phone.extension:
        filename = f"{phone.extension}.xml"
        files.append(_write(filename, output_dir))
        _write(filename, archive_dir)

    # Generate file for eth0 MAC address
    if phone.mac_eth0:
        eth0_filename = f"cfg{phone.mac_eth0}.xml"
        files.append(_write(eth0_filename, output_dir))
        _write(eth0_filename, archive_dir)

    # Generate file for wlan MAC address
    if phone.mac_wlan:
        wlan_filename = f"cfg{phone.mac_wlan}.xml"
        files.append(_write(wlan_filename, output_dir))
        _write(wlan_filename, archive_dir)

    return files
