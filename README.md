# GrandStream Config Manager

A local web app for managing provisioning XML configurations for GrandStream GRP2612W and GRP2613 VoIP phones, aimed at simplifying deployments for small office and residential environments.

**Security Warning:** This software is intended to run locally and has not been hardened for security. You have been warned, use at your own discretion.

## Screenshots

Static HTML mockups are in the [mockups/](mockups/) folder:

| File | Screen |
|---|---|
| [01-phones.html](mockups/01-phones.html) | Phone Inventory |
| [02-phone-edit.html](mockups/02-phone-edit.html) | Phone Edit — SIP tab |
| [02b-phone-edit-wifi.html](mockups/02b-phone-edit-wifi.html) | Phone Edit — WiFi tab |
| [03-phonebook.html](mockups/03-phonebook.html) | Phone Book |
| [04-settings.html](mockups/04-settings.html) | Settings |

## Scope

This tool **generates XML configuration files only**. It does not include a TFTP server, and it does not provision phones directly. Serving the generated files to phones (via TFTP or HTTP) is outside the scope of this project and must be handled separately.

## Features

- **Phone inventory** — import phones via CSV or existing XML config files
- **Per-phone configuration** — SIP accounts (up to 6), WiFi SSIDs (up to 4), virtual programmable keys, phonebook, display/screensaver, and provisioning settings
- **XML generation** — generate delta provisioning XML per phone, selectable from the inventory
- **Phone Book** — auto-generated from the phone inventory, with support for additional custom entries
- **Settings** — configurable output directory and default SIP/phonebook server addresses

## Requirements

- Python 3.9+
- Dependencies listed in `requirements.txt`

## Setup

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Then open [http://localhost:8000](http://localhost:8000).

## CSV Import Format

```
account,subscriber_name,subscriber_id,model,serial,hw_passwd,eth0,wlan
Office,Alice,1000,GRP2612W,aabbcc001122,admin123,aabbcc001122,aabbcc001133
```

| Column | Description |
|---|---|
| `account` | Group / account name |
| `subscriber_name` | Display name shown on the phone |
| `subscriber_id` | SIP extension / user ID |
| `model` | `GRP2612W` or `GRP2613` |
| `serial` | Device serial number (used as upsert key) |
| `hw_passwd` | Factory/hardware admin password |
| `eth0` | Ethernet MAC address |
| `wlan` | WiFi MAC address (optional) |

## XML Output

Generated files are written to the configured output directory (default `./output`). Files are named by extension, e.g. `1000.xml`. The phonebook is written as `phonebook.xml`.

### Serving via TFTP

Grandstream phones fetch their config by MAC address — they request `cfg<mac>.xml` (lowercase, no separators). Create symbolic links from each phone's generated XML to its MAC-based filenames:

```bash
# For a phone with extension 1000, eth0 mac aabbcc001122, wlan mac aabbcc001133
ln -s 1000.xml cfgaabbcc001122.xml   # ethernet MAC
ln -s 1000.xml cfgaabbcc001133.xml   # wifi MAC
```

If you have many phones, you can script it from the CSV:

```bash
# Using the example CSV row: Office,Alice,1000,GRP2612W,aabbcc001122,admin123,aabbcc001122,aabbcc001133
while IFS=, read -r account name ext model serial passwd eth0 wlan; do
    [ "$account" = "account" ] && continue   # skip header
    ln -sf "${ext}.xml" "cfg${eth0}.xml"
    [ -n "$wlan" ] && ln -sf "${ext}.xml" "cfg${wlan}.xml"
done < phones.csv
```

Run both the symlink commands and the script from within the TFTP server root directory — that is the directory your TFTP server serves files from. The symlinks and the generated XML files must all reside there together.

## Phone Models

| Model | WiFi | VPK Slots |
|---|---|---|
| GRP2612W | Yes (up to 4 SSIDs) | 4 |
| GRP2613 | No | 6 |

## Project Structure

```
main.py                 FastAPI routes
models.py               SQLAlchemy models
database.py             DB init and migrations
csv_importer.py         CSV import logic
xml_generator.py        Provisioning XML generation
xml_importer.py         XML config import/parsing
phonebook_generator.py  Phonebook XML generation
templates/              Jinja2 HTML templates
output/                 Generated XML files (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
