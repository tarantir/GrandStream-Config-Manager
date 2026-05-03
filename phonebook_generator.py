import os
from datetime import datetime
import xml.etree.ElementTree as ET


def _timestamped_archive_dir(output_dir: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archive_dir = os.path.join(output_dir, "archive", timestamp)
    os.makedirs(archive_dir, exist_ok=True)
    return archive_dir


def generate_phonebook_xml(phones: list, entries: list) -> str:
    root = ET.Element("AddressBook")

    g1 = ET.SubElement(root, "pbgroup")
    ET.SubElement(g1, "id").text = "1"
    ET.SubElement(g1, "name").text = "Blacklist"

    g2 = ET.SubElement(root, "pbgroup")
    ET.SubElement(g2, "id").text = "2"
    ET.SubElement(g2, "name").text = "Whitelist"

    # Build unified contact list: phones first, then custom entries
    contacts = []
    for phone in phones:
        contacts.append({
            "name": phone.subscriber_name or phone.display_name or phone.extension or "",
            "number": phone.extension or "",
            "account_index": 1,
            "frequent": 0,
        })
    for entry in entries:
        contacts.append({
            "name": entry.first_name,
            "number": entry.phone_number,
            "account_index": entry.account_index,
            "frequent": entry.frequent,
        })

    contacts.sort(key=lambda c: c["name"].lower())

    for i, c in enumerate(contacts, start=1):
        contact = ET.SubElement(root, "Contact")
        ET.SubElement(contact, "id").text = str(i)
        ET.SubElement(contact, "FirstName").text = c["name"]
        ET.SubElement(contact, "Frequent").text = str(c["frequent"])
        ph = ET.SubElement(contact, "Phone")
        ph.set("type", "Work")
        ET.SubElement(ph, "phonenumber").text = c["number"]
        ET.SubElement(ph, "accountindex").text = str(c["account_index"])
        ET.SubElement(contact, "Primary").text = "0"

    ET.indent(root, space="    ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def write_phonebook(phones: list, entries: list, output_dir: str) -> tuple[str, str]:
    xml_content = generate_phonebook_xml(phones, entries)
    os.makedirs(output_dir, exist_ok=True)
    archive_dir = _timestamped_archive_dir(output_dir)
    filepath = os.path.abspath(os.path.join(output_dir, "phonebook.xml"))
    archive_filepath = os.path.abspath(os.path.join(archive_dir, "phonebook.xml"))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(xml_content)
    with open(archive_filepath, "w", encoding="utf-8") as f:
        f.write(xml_content)
    return "phonebook.xml", filepath
