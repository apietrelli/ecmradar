"""
ECM Field Inspector
===================
Utility per ispezionare i nomi reali dei campi ASP.NET sulla pagina AGENAS.
Da eseguire UNA VOLTA per calibrare il mapping dei campi nello scraper.

Uso:
    python inspect_fields.py
    python inspect_fields.py --save
"""

import requests
from bs4 import BeautifulSoup
import json
import sys

BASE_URL = "https://ape.agenas.it/Tools/Eventi.aspx"

def inspect():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    })

    print(f"Fetching {BASE_URL}...")
    resp = session.get(BASE_URL, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    print(f"\n{'='*70}")
    print("CAMPI INPUT (name → type, id)")
    print(f"{'='*70}")

    fields = {}
    for tag in soup.find_all(["input", "select", "textarea"]):
        name = tag.get("name", "")
        field_type = tag.get("type", tag.name)
        field_id = tag.get("id", "")
        value = tag.get("value", "")[:50]

        if name and not name.startswith("__"):
            fields[name] = {
                "type": field_type,
                "id": field_id,
                "sample_value": value
            }
            print(f"  {name}")
            print(f"    type={field_type}  id={field_id}")
            if tag.name == "select":
                options = tag.find_all("option")[:5]
                for opt in options:
                    print(f"    option: value={opt.get('value', '')} → {opt.get_text(strip=True)[:40]}")
            elif value:
                print(f"    value={value}")

    # Campi nascosti ASP.NET
    print(f"\n{'='*70}")
    print("CAMPI NASCOSTI ASP.NET")
    print(f"{'='*70}")
    for tag in soup.find_all("input", {"type": "hidden"}):
        name = tag.get("name", "")
        value = tag.get("value", "")[:80]
        print(f"  {name} = {value}...")

    # Bottoni
    print(f"\n{'='*70}")
    print("BOTTONI")
    print(f"{'='*70}")
    for tag in soup.find_all(["input", "button"], {"type": ["submit", "button"]}):
        name = tag.get("name", "")
        value = tag.get("value", tag.get_text(strip=True))
        print(f"  {name} = {value}")

    # Tabelle (per capire la struttura risultati)
    print(f"\n{'='*70}")
    print("TABELLE")
    print(f"{'='*70}")
    for i, table in enumerate(soup.find_all("table")):
        table_id = table.get("id", "no-id")
        table_class = table.get("class", [])
        rows = table.find_all("tr")
        print(f"  Table #{i}: id={table_id} class={table_class} rows={len(rows)}")
        if rows:
            first_row_cells = rows[0].find_all(["th", "td"])
            headers = [c.get_text(strip=True)[:30] for c in first_row_cells]
            print(f"    Headers: {headers}")

    # Link con postback (paginazione)
    print(f"\n{'='*70}")
    print("LINK CON POSTBACK")
    print(f"{'='*70}")
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "__doPostBack" in href:
            text = link.get_text(strip=True)
            print(f"  [{text}] → {href[:80]}")

    if "--save" in sys.argv:
        output = {
            "url": BASE_URL,
            "fields": fields,
        }
        with open("field_mapping.json", "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n→ Mapping salvato in field_mapping.json")

    return fields


if __name__ == "__main__":
    inspect()
