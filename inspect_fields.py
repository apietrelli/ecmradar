"""
ECM Field Inspector
===================
Utility per ispezionare i nomi reali dei campi ASP.NET sulla pagina AGENAS.
Da eseguire UNA VOLTA per calibrare il mapping dei campi nello scraper.

Usa la stessa ASPNetSession dello scraper (flusso cookie a due step),
così la pagina ispezionata è identica a quella che lo scraper vede
realmente durante la ricerca — non la versione con il banner cookie.

Uso:
    python inspect_fields.py
    python inspect_fields.py --save
"""

import json
import sys

from scraper import ASPNetSession, BASE_URL, FORM_PREFIX


# Campi chiave usati dallo scraper: la risoluzione per suffisso deve trovarli
KEY_FIELDS = [
    "tbTitoloEvento", "tbDenominazioneProvider", "tbIDEvento", "tbIDProvider",
    "tbDataInizio", "tbDataFine",
    "ddlProfessione", "ddlRegioni", "ddlTipologiaEvento", "ddlObiettivoFormativo",
]


def inspect():
    asp = ASPNetSession()
    print(f"Fetching {BASE_URL} (con flusso cookie a due step)...")
    soup = asp.get_page()

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

    # Bottoni (come catturati dalla sessione dello scraper)
    print(f"\n{'='*70}")
    print("BOTTONI (catturati da ASPNetSession)")
    print(f"{'='*70}")
    for name, info in asp._buttons.items():
        print(f"  {name} = {info.get('value', '')} [{info.get('type', '')}]")

    # Verifica risoluzione dei campi chiave usati dallo scraper
    print(f"\n{'='*70}")
    print("RISOLUZIONE CAMPI CHIAVE (suffisso → nome reale)")
    print(f"{'='*70}")
    resolution = {}
    for suffix in KEY_FIELDS:
        resolved = asp._resolve_field(suffix, "(NON TROVATO)")
        resolution[suffix] = resolved
        marker = "✓" if resolved != "(NON TROVATO)" else "✗"
        print(f"  {marker} {suffix:30s} → {resolved}")
    btn_name, btn_kind = asp._find_search_button()
    resolution["btnCerca"] = btn_name
    print(f"  {'✓' if btn_name else '✗'} {'btnCerca':30s} → {btn_name} [{btn_kind}]")
    if any(v == "(NON TROVATO)" for v in resolution.values()):
        print(f"\n  ⚠ Alcuni campi non sono stati trovati: la struttura del sito")
        print(f"    è cambiata oltre il prefisso (attuale: {FORM_PREFIX}).")
        print(f"    Aggiorna i suffissi in scraper.py → ASPNetSession.search().")

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
            "buttons": asp._buttons,
            "key_field_resolution": resolution,
        }
        with open("field_mapping.json", "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n→ Mapping salvato in field_mapping.json")

    return fields


if __name__ == "__main__":
    inspect()
