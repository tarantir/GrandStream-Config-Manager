import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import AppSetting, Phone, PhoneConfig, PhonebookEntry, SipAccount, VpkKey, WifiSsid
from xml_generator import generate_xml, write_xml
from csv_importer import import_csv, export_csv
from xml_importer import import_xml_bulk, import_xml_for_phone, parse_xml
from phonebook_generator import generate_phonebook_xml, write_phonebook


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# ── Flash message helpers ─────────────────────────────────────────────────────

def set_flash(response: Response, message: str, category: str = "info"):
    response.set_cookie("flash_msg", json.dumps({"msg": message, "cat": category}), max_age=10)


def get_flash(flash_cookie: Optional[str] = Cookie(default=None, alias="flash_msg")) -> Optional[dict]:
    if flash_cookie:
        try:
            return json.loads(flash_cookie)
        except Exception:
            pass
    return None


def get_output_dir(db: Session) -> str:
    setting = db.query(AppSetting).filter(AppSetting.key == "output_dir").first()
    return setting.value if setting else "./output"


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), flash=Depends(get_flash)):
    phones = db.query(Phone).order_by(Phone.extension).all()
    response = templates.TemplateResponse("phones.html", {
        "request": request,
        "phones": phones,
        "flash": flash,
    })
    response.delete_cookie("flash_msg")
    return response


# ── CSV Import ────────────────────────────────────────────────────────────────

@app.post("/import")
async def import_phones(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    result = import_csv(content, db)
    msg = f"Imported {result['imported']} new, updated {result['updated']} existing phones."
    if result["errors"]:
        msg += f" {len(result['errors'])} error(s)."
    category = "error" if result["errors"] and result["imported"] == 0 else "success"
    response = RedirectResponse(url="/", status_code=303)
    set_flash(response, msg, category)
    return response


@app.get("/export")
async def export_phones(db: Session = Depends(get_db)):
    phones = db.query(Phone).order_by(Phone.extension).all()
    csv_bytes = export_csv(phones)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=phones.csv"},
    )


# ── XML Import ────────────────────────────────────────────────────────────────

@app.post("/import-xml")
async def import_xml_files(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    file_pairs = [(f.filename, await f.read()) for f in files]
    result = import_xml_bulk(file_pairs, db)
    count = len(result["imported"])
    err_count = len(result["errors"])
    msg = f"Imported config from {count} XML file{'s' if count != 1 else ''}."
    if err_count:
        msg += f" {err_count} error{'s' if err_count != 1 else ''}: " + "; ".join(result["errors"])
    category = "error" if err_count and count == 0 else "success"
    response = RedirectResponse(url="/", status_code=303)
    set_flash(response, msg, category)
    return response


@app.post("/phones/{phone_id}/import-xml")
async def import_xml_single(phone_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if not phone:
        return JSONResponse({"error": "Phone not found"}, status_code=404)
    content = await file.read()
    try:
        result = import_xml_for_phone(content, phone, db)
        return JSONResponse({"ok": True, **result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Phone edit ────────────────────────────────────────────────────────────────

@app.get("/phones/{phone_id}/edit", response_class=HTMLResponse)
async def edit_phone(request: Request, phone_id: int, db: Session = Depends(get_db), flash=Depends(get_flash)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if not phone:
        return RedirectResponse(url="/", status_code=302)

    sip_accounts = {a.account_num: a for a in phone.sip_accounts}
    wifi_ssids = {s.ssid_num: s for s in phone.wifi_ssids}
    response = templates.TemplateResponse("phone_edit.html", {
        "request": request,
        "phone": phone,
        "config": phone.config,
        "vpk_keys": phone.vpk_keys,
        "sip_accounts": sip_accounts,
        "wifi_ssids": wifi_ssids,
        "flash": flash,
    })
    response.delete_cookie("flash_msg")
    return response


@app.post("/phones/{phone_id}/config")
async def save_phone_config(request: Request, phone_id: int, db: Session = Depends(get_db)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if not phone:
        return RedirectResponse(url="/", status_code=302)

    form_data = await request.form()

    # ── SIP accounts ──────────────────────────────────────────────────────────
    existing_accounts = {a.account_num: a for a in phone.sip_accounts}
    for n in range(1, 7):
        acct = existing_accounts.get(n)
        if acct is None:
            acct = SipAccount(phone_id=phone_id, account_num=n)
            db.add(acct)
        acct.enabled = f"acct_{n}_enabled" in form_data
        acct.display_name = form_data.get(f"acct_{n}_display_name", "")
        acct.subscriber_name = form_data.get(f"acct_{n}_subscriber_name", "")
        acct.password        = form_data.get(f"acct_{n}_password", "")
        acct.extension       = form_data.get(f"acct_{n}_extension", "")
        acct.sip_server_1 = form_data.get(f"acct_{n}_sip_server_1", "192.168.1.1")
        acct.sip_server_2 = form_data.get(f"acct_{n}_sip_server_2", "pbx.example.com")
        acct.sip_server_3 = form_data.get(f"acct_{n}_sip_server_3", "")
        acct.voicemail_number = form_data.get(f"acct_{n}_voicemail_number", "*97")

    # Sync Phone.display_name from account 1 subscriber_name for the dashboard
    if existing_accounts.get(1):
        phone.display_name = form_data.get("acct_1_subscriber_name", "") or phone.extension
    phone.updated_at = datetime.utcnow()

    # ── Phone-level config ────────────────────────────────────────────────────
    cfg = phone.config
    if not cfg:
        cfg = PhoneConfig(phone_id=phone_id)
        db.add(cfg)

    cfg.phonebook_server = form_data.get("phonebook_server", "")
    cfg.phonebook_mode = form_data.get("phonebook_mode", "")
    try:
        cfg.phonebook_interval = int(form_data.get("phonebook_interval", 720))
    except (ValueError, TypeError):
        pass
    cfg.phonebook_protocol = form_data.get("phonebook_protocol", "TFTP")
    cfg.hotdesking_server = form_data.get("hotdesking_server", "")
    cfg.hotdesking_type = form_data.get("hotdesking_type", "TFTP")
    cfg.wifi_ssid = form_data.get("wifi_ssid", "")
    cfg.wifi_psk = form_data.get("wifi_psk", "")
    cfg.wifi_band = form_data.get("wifi_band", "Auto")
    cfg.wifi_key_mgmt = form_data.get("wifi_key_mgmt", "WPA_PSK")
    cfg.wallpaper_color = form_data.get("wallpaper_color", "#000000")
    cfg.wallpaper_source = form_data.get("wallpaper_source", "ColorBackground")
    cfg.screensaver_enabled = "screensaver_enabled" in form_data
    cfg.screensaver_source = form_data.get("screensaver_source", "Default")
    try:
        cfg.screensaver_timeout = int(form_data.get("screensaver_timeout", 3))
        cfg.screensaver_downloadxmlinterval = int(form_data.get("screensaver_downloadxmlinterval", 0))
    except (ValueError, TypeError):
        pass
    cfg.screensaver_showdatetime = "screensaver_showdatetime" in form_data
    cfg.screensaver_serverpath = form_data.get("screensaver_serverpath", "")
    cfg.screensaver_useprogrammablekeys = "screensaver_useprogrammablekeys" in form_data
    cfg.sip_notify_challenge = "sip_notify_challenge" in form_data
    cfg.vpn_enabled    = "vpn_enabled" in form_data
    cfg.vpn_server     = form_data.get("vpn_server", "")
    try:
        cfg.vpn_port   = int(form_data.get("vpn_port", 1194))
    except (ValueError, TypeError):
        pass
    cfg.vpn_transport  = form_data.get("vpn_transport", "udp")
    cfg.vpn_cipher     = form_data.get("vpn_cipher", "AES256GCM")
    cfg.vpn_ca         = form_data.get("vpn_ca", "")
    cfg.vpn_cert       = form_data.get("vpn_cert", "")
    cfg.vpn_client_key = form_data.get("vpn_client_key", "")
    cfg.datetime_date_format = form_data.get("datetime_date_format", "yyyy-mm-dd")
    cfg.datetime_time_format = form_data.get("datetime_time_format", "24Hour")
    cfg.datetime_show_on_statusbar = form_data.get("datetime_show_on_statusbar", "fullDate")

    if phone.model == "GRP2613":
        cfg.wifi_enabled = False
    else:
        cfg.wifi_enabled = "wifi_enabled" in form_data
        cfg.wifi_band = form_data.get("wifi_band", "Auto")

    # ── WiFi SSIDs ────────────────────────────────────────────────────────────
    existing_ssids = {s.ssid_num: s for s in phone.wifi_ssids}
    for n in range(1, 5):
        s = existing_ssids.get(n)
        if s is None:
            s = WifiSsid(phone_id=phone_id, ssid_num=n)
            db.add(s)
        s.enabled = f"ssid_{n}_enabled" in form_data
        s.essid = form_data.get(f"ssid_{n}_essid", "")
        s.psk = form_data.get(f"ssid_{n}_psk", "")
        s.key_mgmt = form_data.get(f"ssid_{n}_key_mgmt", "WPA_PSK")
        s.hidden = f"ssid_{n}_hidden" in form_data
        try:
            s.priority = int(form_data.get(f"ssid_{n}_priority", 0))
        except (ValueError, TypeError):
            s.priority = 0

    # ── VPK keys ──────────────────────────────────────────────────────────────
    max_slots = 6 if phone.model == "GRP2613" else 4
    existing_vpks = {v.slot: v for v in phone.vpk_keys}

    for slot in range(1, max_slots + 1):
        keymode = form_data.get(f"vpk_{slot}_keymode", "None")
        description = form_data.get(f"vpk_{slot}_description", "")
        value = form_data.get(f"vpk_{slot}_value", "")
        account = form_data.get(f"vpk_{slot}_account", "Account1")

        if slot in existing_vpks:
            vpk = existing_vpks[slot]
            vpk.keymode = keymode
            vpk.description = description
            vpk.value = value
            vpk.account = account
        else:
            vpk = VpkKey(
                phone_id=phone_id,
                slot=slot,
                keymode=keymode,
                description=description,
                value=value,
                account=account,
            )
            db.add(vpk)

    db.commit()

    response = RedirectResponse(url=f"/phones/{phone_id}/edit", status_code=303)
    set_flash(response, "Configuration saved.", "success")
    return response


# ── Delete phone ──────────────────────────────────────────────────────────────

@app.delete("/phones/{phone_id}")
async def delete_phone(phone_id: int, db: Session = Depends(get_db)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if phone:
        db.delete(phone)
        db.commit()
    return JSONResponse({"ok": True})


# ── XML generation ────────────────────────────────────────────────────────────

@app.get("/phones/{phone_id}/preview")
async def preview_phone_xml(phone_id: int, db: Session = Depends(get_db)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if not phone or not phone.config:
        return JSONResponse({"error": "Phone not found"}, status_code=404)
    xml_content = generate_xml(phone)
    filename = f"cfg{phone.mac_eth0}.xml" if phone.mac_eth0 else f"{phone.extension}.xml"
    return JSONResponse({"xml": xml_content, "filename": filename})


@app.post("/phones/{phone_id}/generate")
async def generate_phone_xml(phone_id: int, db: Session = Depends(get_db)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if not phone or not phone.config:
        return JSONResponse({"error": "Phone not found"}, status_code=404)

    output_dir = get_output_dir(db)
    files = write_xml(phone, output_dir)
    xml_content = generate_xml(phone)

    return JSONResponse({"files": files, "xml": xml_content})


@app.post("/generate-selected")
async def generate_selected(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    phone_ids = data.get("phone_ids", [])
    phones = db.query(Phone).filter(Phone.id.in_(phone_ids)).all()
    output_dir = get_output_dir(db)
    generated = []
    errors = []

    for phone in phones:
        if not phone.config:
            errors.append(f"{phone.extension}: no config")
            continue
        try:
            files = write_xml(phone, output_dir)
            generated.extend([f[0] for f in files])  # filenames
        except Exception as e:
            errors.append(f"{phone.extension}: {e}")

    return JSONResponse({"generated": generated, "errors": errors})


@app.get("/phones/{phone_id}/xml")
async def get_phone_xml(phone_id: int, db: Session = Depends(get_db)):
    phone = db.query(Phone).filter(Phone.id == phone_id).first()
    if not phone or not phone.config:
        return Response("Not found", status_code=404, media_type="text/plain")
    xml_content = generate_xml(phone)
    return Response(xml_content, media_type="text/plain")


# ── Phone Book ────────────────────────────────────────────────────────────────

@app.get("/phonebook", response_class=HTMLResponse)
async def phonebook_page(request: Request, db: Session = Depends(get_db), flash=Depends(get_flash)):
    phones = db.query(Phone).order_by(Phone.extension).all()
    entries = db.query(PhonebookEntry).order_by(PhonebookEntry.first_name).all()
    response = templates.TemplateResponse("phonebook.html", {
        "request": request,
        "phones": phones,
        "entries": entries,
        "flash": flash,
    })
    response.delete_cookie("flash_msg")
    return response


@app.get("/phonebook/xml")
async def get_phonebook_xml(db: Session = Depends(get_db)):
    phones = db.query(Phone).order_by(Phone.extension).all()
    entries = db.query(PhonebookEntry).order_by(PhonebookEntry.first_name).all()
    xml_content = generate_phonebook_xml(phones, entries)
    return Response(xml_content, media_type="text/plain")


@app.post("/phonebook/generate")
async def generate_phonebook(db: Session = Depends(get_db)):
    phones = db.query(Phone).order_by(Phone.extension).all()
    entries = db.query(PhonebookEntry).order_by(PhonebookEntry.first_name).all()
    output_dir = get_output_dir(db)
    filename, filepath = write_phonebook(phones, entries, output_dir)
    xml_content = generate_phonebook_xml(phones, entries)
    return JSONResponse({"filename": filename, "path": filepath, "xml": xml_content})


@app.post("/phonebook/entries")
async def add_phonebook_entry(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    entry = PhonebookEntry(
        first_name=data.get("first_name", "").strip(),
        phone_number=data.get("phone_number", "").strip(),
        account_index=int(data.get("account_index", 1)),
        frequent=int(data.get("frequent", 0)),
    )
    if not entry.first_name or not entry.phone_number:
        return JSONResponse({"error": "Name and phone number are required"}, status_code=400)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return JSONResponse({"ok": True, "id": entry.id, "first_name": entry.first_name,
                         "phone_number": entry.phone_number, "account_index": entry.account_index})


@app.put("/phonebook/entries/{entry_id}")
async def update_phonebook_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
    entry = db.query(PhonebookEntry).filter(PhonebookEntry.id == entry_id).first()
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)
    data = await request.json()
    first_name = data.get("first_name", "").strip()
    phone_number = data.get("phone_number", "").strip()
    if not first_name or not phone_number:
        return JSONResponse({"error": "Name and phone number are required"}, status_code=400)
    entry.first_name = first_name
    entry.phone_number = phone_number
    entry.account_index = int(data.get("account_index", entry.account_index))
    db.commit()
    return JSONResponse({"ok": True, "id": entry.id, "first_name": entry.first_name,
                         "phone_number": entry.phone_number, "account_index": entry.account_index})


@app.delete("/phonebook/entries/{entry_id}")
async def delete_phonebook_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(PhonebookEntry).filter(PhonebookEntry.id == entry_id).first()
    if entry:
        db.delete(entry)
        db.commit()
    return JSONResponse({"ok": True})


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db), flash=Depends(get_flash)):
    settings = {s.key: s.value for s in db.query(AppSetting).all()}
    response = templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "flash": flash,
    })
    response.delete_cookie("flash_msg")
    return response


@app.post("/settings")
async def save_settings(
    request: Request,
    db: Session = Depends(get_db),
    output_dir: str = Form("./output"),
    default_sip_server_1: str = Form("192.168.1.1"),
    default_sip_server_2: str = Form("pbx.example.com"),
    default_phonebook_server: str = Form("192.168.1.1"),
):
    updates = {
        "output_dir": output_dir,
        "default_sip_server_1": default_sip_server_1,
        "default_sip_server_2": default_sip_server_2,
        "default_phonebook_server": default_phonebook_server,
    }
    for key, value in updates.items():
        setting = db.query(AppSetting).filter(AppSetting.key == key).first()
        if setting:
            setting.value = value
        else:
            db.add(AppSetting(key=key, value=value))
    db.commit()

    response = RedirectResponse(url="/settings", status_code=303)
    set_flash(response, "Settings saved.", "success")
    return response
