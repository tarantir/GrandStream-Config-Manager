import csv
import io
from datetime import datetime
from sqlalchemy.orm import Session
from models import Phone, PhoneConfig, SipAccount, VpkKey, WifiSsid


def _normalize_mac(raw: str) -> str | None:
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip().replace(":", "").replace("-", "").replace(".", "").lower()
    return cleaned if cleaned else None


def import_csv(content: bytes, db: Session) -> dict:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    imported = 0
    updated = 0
    errors = []

    for row in reader:
        try:
            account_name   = row.get("account", "").strip()       # → group_name + account.1.name
            subscriber_name = row.get("subscriber_name", "").strip() # → display_name + subscriber.name
            extension      = row.get("subscriber_id", "").strip()  # → extension / SIP userid
            model          = row.get("model", "").strip()
            serial         = row.get("serial", "").strip()
            password       = row.get("hw_passwd", "").strip()
            mac_eth0       = _normalize_mac(row.get("eth0", ""))
            mac_wlan       = _normalize_mac(row.get("wlan", ""))

            if not serial:
                errors.append("Row skipped: missing serial")
                continue

            existing = db.query(Phone).filter(Phone.serial == serial).first()

            if existing:
                existing.group_name      = account_name
                existing.title           = f"{extension} {model}"
                existing.extension       = extension
                existing.model           = model
                existing.mac_eth0        = mac_eth0
                existing.mac_wlan        = mac_wlan
                existing.factory_password = password
                existing.updated_at      = datetime.utcnow()
                phone = existing
                updated += 1

                # Update SIP account 1 identity fields if it exists
                acct1 = next((a for a in phone.sip_accounts if a.account_num == 1), None)
                if acct1:
                    acct1.display_name    = account_name
                    acct1.subscriber_name = subscriber_name
                    acct1.extension       = extension
            else:
                phone = Phone(
                    group_name=account_name,
                    title=f"{extension} {model}",
                    extension=extension,
                    model=model,
                    serial=serial,
                    mac_eth0=mac_eth0,
                    mac_wlan=mac_wlan,
                    factory_password=password,
                )
                db.add(phone)
                db.flush()
                imported += 1

            # PhoneConfig
            if not phone.config:
                db.add(PhoneConfig(
                    phone_id=phone.id,
                    wifi_enabled=(model != "GRP2613"),
                ))

            # WiFi SSIDs
            if not phone.wifi_ssids:
                db.add(WifiSsid(phone_id=phone.id, ssid_num=1, enabled=True))
                for n in range(2, 5):
                    db.add(WifiSsid(phone_id=phone.id, ssid_num=n, enabled=False))

            # SIP accounts
            if not phone.sip_accounts:
                db.add(SipAccount(
                    phone_id=phone.id, account_num=1, enabled=True,
                    display_name=account_name,
                    subscriber_name=subscriber_name,
                    extension=extension,
                ))
                for n in range(2, 7):
                    db.add(SipAccount(
                        phone_id=phone.id, account_num=n, enabled=False,
                    ))

            # VPK keys
            if not phone.vpk_keys:
                max_slots = 6 if model == "GRP2613" else 4
                for slot in range(1, max_slots + 1):
                    db.add(VpkKey(
                        phone_id=phone.id,
                        slot=slot,
                        keymode="Line" if slot == 1 else "None",
                        description=subscriber_name if slot == 1 else "",
                        value="",
                        account="Account1",
                    ))

        except Exception as e:
            errors.append(f"Row error: {e}")

    db.commit()
    return {"imported": imported, "updated": updated, "errors": errors}


def export_csv(phones: list[Phone]) -> bytes:
    fieldnames = [
        "account",
        "subscriber_name",
        "subscriber_id",
        "model",
        "serial",
        "hw_passwd",
        "eth0",
        "wlan",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for phone in phones:
        writer.writerow({
            "account": phone.group_name or "",
            "subscriber_name": phone.subscriber_name or phone.display_name or "",
            "subscriber_id": phone.extension or "",
            "model": phone.model or "",
            "serial": phone.serial or "",
            "hw_passwd": phone.factory_password or "",
            "eth0": phone.mac_eth0 or "",
            "wlan": phone.mac_wlan or "",
        })

    return output.getvalue().encode("utf-8-sig")
