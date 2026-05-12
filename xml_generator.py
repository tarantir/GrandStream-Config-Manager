"""
XML provisioning generator for GrandStream GRP261x endpoints.

──────────────────────────────────────────────────────────────────────────────
ARCHITECTURAL DECISION A — pvalue storage
──────────────────────────────────────────────────────────────────────────────
GrandStream firmware assigns each configuration parameter a unique numeric
P-value (e.g., P8387 = "Show Date on Status Bar").  The P-value format is the
canonical identifier used in *.txt provisioning files and in the firmware
release notes.

Decision: P-values are NOT stored in the SQLite database.  They are static
firmware metadata; adding a parameter_catalog table would replicate information
that already lives authoritatively in the OEM XML reference files (data/) and
the firmware release notes PDF.  Instead, the mapping is documented inline in
this file via code comments on each _part() call.  A future enhancement could
read the OEM XML files at startup to build the map automatically, but for now
inline documentation is cleaner and avoids runtime overhead.

──────────────────────────────────────────────────────────────────────────────
ARCHITECTURAL DECISION B — multi-select rendering for enumerated parameters
──────────────────────────────────────────────────────────────────────────────
Several parameters accept a fixed set of string values (e.g.,
phonebook.keyfunction: LocalPhonebook | Default).  These are stored as Text
columns in PhoneConfig and rendered as <select> elements in the Jinja2
templates.  Valid values are documented in code comments and enforced at the
template level.  A separate EnumeratedValue or ParameterCatalog table would
add JOIN complexity without benefit: the set of valid options rarely changes
(only on firmware upgrades), and the <select> already constrains user input.

──────────────────────────────────────────────────────────────────────────────
PVALUE MAP — item.part → firmware P-value
──────────────────────────────────────────────────────────────────────────────
Source: cross-referenced from data/GRP2612W.txt, data/GRP2613.txt, and
        docs/Release_Note_GRP261x_1.0.13.127.pdf.

Account N fields (N=1 shown; offsets apply for accounts 2–4):
  account.1.name                → P3        (acct2 P417, acct3 P517, acct4 P617)
  account.1.enable              → P271      (acct2 P401, acct3 P501, acct4 P601)
  account.1.sip.userid          → P36       (acct2 P404, acct3 P504, acct4 P604)
  account.1.sip.subscriber.name → P270      (acct2 P407, acct3 P507, acct4 P607)
  account.1.sip.subscriber.userid → P35     (acct2 P405, acct3 P505, acct4 P605)
  account.1.sip.subscriber.pass → P34       (acct2 P406, acct3 P506, acct4 P606)
  account.1.sip.voicemail.number → P33      (acct2 P426, acct3 P526, acct4 P626)
  account.1.sip.server.1.address → P47      (acct2 P402, acct3 P502, acct4 P602)
  account.1.sip.server.2.address → P2312    (acct2 P2412, acct3 P2512, acct4 P2612)

WiFi:
  network.wifi.countryCode.public → P7831
  network.wifi.enable             → P7800
  network.wifi.ssid.0.essid       → P83000  (ssid.1 P83100, ssid.2 P83200, ssid.3 P83300)
  network.wifi.ssid.0.key_management → P83002
  network.wifi.ssid.0.psk         → P83003
  network.wifi.ssid.0.eap_method  → P83004
  network.wifi.ssid.0.hidden      → P83050

OpenVPN:
  network.openvpn.enable   → P7050
  network.openvpn.server   → P7051
  network.openvpn.port     → P7052
  network.openvpn.ca       → P9902
  network.openvpn.cert     → P9903
  network.openvpn.clientKey → P9904

VPK keys (slot N):
  pks.vpk.N.keyMode      → P1363 + (N-1)*2
  pks.vpk.N.account      → P1364 + (N-1)*2
  pks.vpk.N.description  → P1465 + (N-1)*2
  pks.vpk.N.value        → P1466 + (N-1)*2

Phonebook / date-time / display:
  sip.notify.challenge         → P4428  (0=No, 1=Yes)
  phonebook.download.mode      → P330
  phonebook.download.server    → P331
  phonebook.download.interval  → P332
  phonebook.keyFunction        → P1526  (1=Default, 2=LocalPhonebook)
  phonebook.sortBy             → P2914  (1=FirstName, 2=LastName)
  phonebook.defaultSearchMode  → P2918  (0=QuickMatch, 1=ExactMatch)
  datetime.format.date         → P102
  datetime.format.time         → P122
  datetime.showOnStatusBar     → P8387  (0=No Date, 1=Short Date, 2=Full Date)
  lcd.wallpaper.source         → P2916
  lcd.screensaver.enable       → P2970  (0=disabled, 1=enabled)

Idle/Dialing softkey layout (Keys tab — pre-date pvalue docs, not in release notes):
  pks.scsoftkey.1 → mode           → pvalue unknown (text: Default, Phonebook, History, …)
  softkey.idlelayout.state → inidle → pvalue unknown (comma-separated token list)
  softkeys.layout → enable          → pvalue unknown (Yes/No)
  softkeys.layout.state → indialing → pvalue unknown (comma-separated token list)
  pks.softkey.1 → keymode           → pvalue unknown (text: Default, Phonebook, …)

Custom softkey slots (N ≥ 2, softkey_slots table):
  pks.scsoftkey.N → mode        → pvalue unknown (e.g. Intercom)
  pks.scsoftkey.N → description → pvalue unknown (display label)
  pks.scsoftkey.N → value       → pvalue unknown (dial string, e.g. *68)
  pks.softkey.N → keymode       → pvalue unknown (same as scsoftkey.N → mode)
  pks.softkey.N → account       → pvalue unknown (e.g. Account1)
  pks.softkey.N → description   → pvalue unknown
  pks.softkey.N → value         → pvalue unknown
"""

import os
from datetime import datetime
import xml.etree.ElementTree as ET
from models import Phone, PhoneConfig, SoftkeySlot, VpkKey


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
    _part(acc, "name", display)      # P3 / P417 / P517 / P617
    _part(acc, "enable", "Yes")      # P271 / P401 / P501 / P601

    sip = ET.SubElement(config, "item")
    sip.set("name", f"account.{n}.sip")
    _part(sip, "userid", ext)        # P36 / P404 / P504 / P604

    sub = ET.SubElement(config, "item")
    sub.set("name", f"account.{n}.sip.subscriber")
    _part(sub, "name", acct.subscriber_name or display)   # P270 / P407 / P507 / P607
    _part(sub, "userid", ext)                             # P35  / P405 / P505 / P605
    _part(sub, "password", acct.password or "")           # P34  / P406 / P506 / P606

    vm = ET.SubElement(config, "item")
    vm.set("name", f"account.{n}.sip.voicemail")
    _part(vm, "number", acct.voicemail_number or "*97")   # P33 / P426 / P526 / P626

    srv1 = ET.SubElement(config, "item")
    srv1.set("name", f"account.{n}.sip.server.1")
    _part(srv1, "address", acct.sip_server_1 or "")       # P47 / P402 / P502 / P602

    srv2 = ET.SubElement(config, "item")
    srv2.set("name", f"account.{n}.sip.server.2")
    _part(srv2, "address", acct.sip_server_2 or "")       # P2312 / P2412 / P2512 / P2612


# key_mgmt string → firmware integer value
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

    # WiFi — skip for GRP2613 (wired-only model) or if disabled
    if phone.model != "GRP2613" and cfg.wifi_enabled:
        cc = ET.SubElement(config, "item")
        cc.set("name", "network.wifi.countryCode")
        _part(cc, "public", cfg.wifi_country_code or "US")   # P7831

        wifi = ET.SubElement(config, "item")
        wifi.set("name", "network.wifi")
        _part(wifi, "enable", "1")   # P7800

        ssid_map = {s.ssid_num: s for s in phone.wifi_ssids}
        for n in range(0, 4):
            s = ssid_map.get(n)
            if not s or not s.essid:
                continue
            ssid = ET.SubElement(config, "item")
            ssid.set("name", f"network.wifi.ssid.{n}")
            # P83000+N*100=essid, P83002+N*100=key_management,
            # P83003+N*100=psk,   P83004+N*100=eap_method, P83050+N*100=hidden
            _part(ssid, "eap_method", "0")
            _part(ssid, "essid", s.essid)
            _part(ssid, "hidden", "1" if s.hidden else "0")
            _part(ssid, "key_management", _KEY_MGMT_NUM.get(s.key_mgmt or "WPA_PSK", "4"))
            _part(ssid, "psk", s.psk or "")

    # VPN
    if cfg.vpn_enabled:
        vpn = ET.SubElement(config, "item")
        vpn.set("name", "network.openvpn")
        _part(vpn, "enable", "Yes")                              # P7050
        _part(vpn, "server", cfg.vpn_server or "")              # P7051
        _part(vpn, "port", str(cfg.vpn_port or 1194))           # P7052
        _part(vpn, "transport", cfg.vpn_transport or "udp")
        _part(vpn, "cipermethod", cfg.vpn_cipher or "AES256GCM")
        _part(vpn, "ca", cfg.vpn_ca or "")                      # P9902
        _part(vpn, "cert", cfg.vpn_cert or "")                  # P9903
        _part(vpn, "clientKey", cfg.vpn_client_key or "")       # P9904
        # NOTE: "mode" part (value "0") intentionally omitted — it maps to
        # OpenVPN client-only mode and is implied by the firmware default;
        # emitting it caused provisioning conflicts on some firmware builds.

    # VPK keys — emit only non-None slots
    for vpk in sorted(phone.vpk_keys, key=lambda k: k.slot):
        if vpk.keymode == "None":
            continue
        item = ET.SubElement(config, "item")
        item.set("name", f"pks.vpk.{vpk.slot}")
        # keyMode: P1363+(slot-1)*2 | account: P1364+(slot-1)*2
        # description: P1465+(slot-1)*2 | value: P1466+(slot-1)*2
        _part(item, "lockmode", "No")
        _part(item, "description", vpk.description or "")
        if vpk.keymode != "Line":
            _part(item, "value", vpk.value or "")
        _part(item, "keymode", vpk.keymode)
        _part(item, "account", vpk.account or "Account1")

    # SIP notify challenge (P4428: 0=No, 1=Yes)
    notify = ET.SubElement(config, "item")
    notify.set("name", "sip.notify")
    _part(notify, "challenge", "Yes" if cfg.sip_notify_challenge else "No")

    # Phonebook download
    pb = ET.SubElement(config, "item")
    pb.set("name", "phonebook.download")
    _part(pb, "interval", str(cfg.phonebook_interval or 720))   # P332
    _part(pb, "mode", cfg.phonebook_mode or "EnabledUseTFTP")   # P330
    _part(pb, "server", cfg.phonebook_server or "")             # P331

    # Phonebook behaviour
    pbs = ET.SubElement(config, "item")
    pbs.set("name", "phonebook")
    _part(pbs, "defaultsearchmode", cfg.phonebook_defaultsearchmode or "QuickMatch")  # P2918
    _part(pbs, "keyfunction", cfg.phonebook_keyfunction or "LocalPhonebook")          # P1526
    _part(pbs, "sortby", cfg.phonebook_sortby or "FirstName")                         # P2914

    # Date/time format (P102: date, P122: time)
    dtfmt = ET.SubElement(config, "item")
    dtfmt.set("name", "datetime.format")
    _part(dtfmt, "date", cfg.datetime_date_format or "yyyy-mm-dd")
    _part(dtfmt, "time", cfg.datetime_time_format or "24Hour")

    # Date/time status bar (P8387: 0=noDate, 1=shortDate, 2=fullDate)
    dt = ET.SubElement(config, "item")
    dt.set("name", "datetime")
    _part(dt, "showonstatusbar", cfg.datetime_show_on_statusbar or "fullDate")

    # Wallpaper (P2916)
    wp = ET.SubElement(config, "item")
    wp.set("name", "lcd.wallpaper")
    _part(wp, "source", cfg.wallpaper_source or "ColorBackground")

    # Screensaver (P2970: 0=disabled, 1=enabled)
    ss = ET.SubElement(config, "item")
    ss.set("name", "lcd.screensaver")
    _part(ss, "enable", "Yes" if cfg.screensaver_enabled else "No")

    # Web access security — session timeouts
    sec = ET.SubElement(config, "item")
    sec.set("name", "security.webaccess.session")
    _part(sec, "timeout",       str(cfg.webaccess_timeout       if cfg.webaccess_timeout       is not None else 60))
    _part(sec, "authtimeout",   str(cfg.webaccess_authtimeout   if cfg.webaccess_authtimeout   is not None else 60))
    _part(sec, "accesstimeout", str(cfg.webaccess_accesstimeout if cfg.webaccess_accesstimeout is not None else 60))

    # Idle Screen Customizations (pvalues unknown — older params predating pvalue docs)
    idle_layout_enable = cfg.idle_softkey_layout_enable or "Yes"
    idl = ET.SubElement(config, "item")
    idl.set("name", "softkey.idlelayout")
    _part(idl, "enable", idle_layout_enable)                       # pvalue unknown
    if idle_layout_enable == "Yes":
        idle_layout = ET.SubElement(config, "item")
        idle_layout.set("name", "softkey.idlelayout.state")
        _part(idle_layout, "inidle", cfg.idle_layout_state or "Next,Custom1,Custom2,Custom3,History,ForwardAll,Redial")  # pvalue unknown

    # Dialing Screen Customizations (pvalues unknown — older params predating pvalue docs)
    dialing_enable = cfg.dialing_softkeys_enable or "Yes"
    sk_layout = ET.SubElement(config, "item")
    sk_layout.set("name", "softkeys.layout")
    _part(sk_layout, "enable", dialing_enable)                     # pvalue unknown
    if dialing_enable == "Yes":
        dial_layout = ET.SubElement(config, "item")
        dial_layout.set("name", "softkeys.layout.state")
        _part(dial_layout, "indialing", cfg.dialing_layout_state or "Custom1,Custom2,Custom3,EndCall,ReConf,ConfRoom,Redial,Dial,Backspace")  # pvalue unknown

    # Custom softkey slots (pks.scsoftkey.N / pks.softkey.N, N ≥ 1; pvalues unknown)
    for sk in sorted(phone.softkey_slots, key=lambda k: k.slot):
        if sk.slot < 1 or sk.slot > 3:
            continue
        if not (sk.idle_mode or sk.dialing_mode or sk.mode or sk.description or sk.value):
            continue

        if sk.idle_mode or sk.mode:
            scskey = ET.SubElement(config, "item")
            scskey.set("name", f"pks.scsoftkey.{sk.slot}")
            _part(scskey, "mode", sk.idle_mode or sk.mode or "Default")
            if sk.description:
                _part(scskey, "description", sk.description)
            if sk.value:
                _part(scskey, "value", sk.value)

        softkey = ET.SubElement(config, "item")
        softkey.set("name", f"pks.softkey.{sk.slot}")
        _part(softkey, "keymode", sk.dialing_mode or sk.mode or "Default")
        _part(softkey, "account", sk.account or "Account1")
        if sk.description:
            _part(softkey, "description", sk.description)
        if sk.value:
            _part(softkey, "value", sk.value)

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
