"""
ECM Batch Scraper - Scraping sistematico per coverage completa
==============================================================
Itera su combinazioni di parametri per massimizzare la copertura.

Strategia:
1. Il sito limita a 180 giorni per ricerca → spezziamo per trimestri
2. Iteriamo per professione × regione per non superare i limiti di risultati
3. Le pagine dettaglio si caricano in un secondo passaggio (lento ma ricco)

Uso:
    python batch_scrape.py --year 2024 --details
    python batch_scrape.py --year 2025 --region Lombardia
    python batch_scrape.py --backfill 2020 2025
"""

import argparse
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from scraper import ECMScraper, ECMDatabase

log = logging.getLogger("ecm_batch")

# Professioni principali (valore dropdown AGENAS)
PROFESSIONS = [
    "Medico Chirurgo",
    "Farmacista",
    "Infermiere",
    "Psicologo",
    "Biologo",
    "Odontoiatra",
    "Veterinario",
    "Fisioterapista",
    "Tecnico Sanitario Laboratorio Biomedico",
    "Tecnico Sanitario Di Radiologia Medica",
    "Tutte Le Professioni",
]

REGIONS = [
    "Piemonte", "Valle D'aosta", "Lombardia",
    "Provincia Autonoma Bolzano", "Provincia Autonoma Trento",
    "Veneto", "Friuli-Venezia Giulia", "Liguria", "Emilia-Romagna",
    "Toscana", "Umbria", "Marche", "Lazio",
    "Abruzzo", "Molise", "Campania", "Puglia",
    "Basilicata", "Calabria", "Sicilia", "Sardegna",
]

EVENT_TYPES = ["FAD", "RES", "FSC", "Blended"]


def generate_date_ranges(year: int) -> list[tuple[str, str]]:
    """Genera intervalli di ~90 giorni (< 180 giorni limit del sito)"""
    ranges = []
    start = datetime(year, 1, 1)
    end = datetime(year, 12, 31)
    current = start
    while current < end:
        period_end = min(current + timedelta(days=89), end)
        ranges.append((
            current.strftime("%d/%m/%Y"),
            period_end.strftime("%d/%m/%Y")
        ))
        current = period_end + timedelta(days=1)
    return ranges


def batch_scrape(
    year: int = 2025,
    region: str = "",
    profession: str = "",
    event_type: str = "",
    fetch_details: bool = False,
    db_path: str = "ecm_database.db"
):
    """Scraping batch per un anno intero"""
    db = ECMDatabase(Path(db_path))
    scraper = ECMScraper(db)

    date_ranges = generate_date_ranges(year)
    total_events = 0

    # Determina combinazioni
    professions = [profession] if profession else [""]  # vuoto = tutte
    regions = [region] if region else [""]

    total_combos = len(date_ranges) * len(professions) * len(regions)
    combo_n = 0

    for date_from, date_to in date_ranges:
        for prof in professions:
            for reg in regions:
                combo_n += 1
                params = {
                    "date_from": date_from,
                    "date_to": date_to,
                }
                if prof:
                    params["profession"] = prof
                if reg:
                    params["region"] = reg
                if event_type:
                    params["event_type"] = event_type

                log.info(f"[{combo_n}/{total_combos}] {date_from}-{date_to}"
                         f" | Prof: {prof or 'Tutte'} | Reg: {reg or 'Tutte'}")

                try:
                    events = scraper.scrape_search(params, fetch_details=fetch_details)
                    total_events += len(events)
                    log.info(f"  → {len(events)} eventi (totale: {total_events})")
                except Exception as e:
                    log.error(f"  ERRORE: {e}")
                    time.sleep(10)  # pausa extra in caso di errore
                    continue

                time.sleep(3)  # pausa tra ricerche

    stats = db.get_stats()
    log.info(f"\n{'='*50}")
    log.info(f"BATCH COMPLETATO - Anno {year}")
    log.info(f"  Eventi totali scraped: {total_events}")
    log.info(f"  DB stats: {json.dumps(stats)}")
    db.close()
    return total_events


def backfill(start_year: int, end_year: int, **kwargs):
    """Backfill su più anni"""
    for year in range(start_year, end_year + 1):
        log.info(f"\n{'#'*60}")
        log.info(f"# BACKFILL ANNO {year}")
        log.info(f"{'#'*60}")
        batch_scrape(year=year, **kwargs)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    parser = argparse.ArgumentParser(description="ECM Batch Scraper")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--region", default="")
    parser.add_argument("--profession", default="")
    parser.add_argument("--type", default="")
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--db", default="ecm_database.db")
    parser.add_argument("--backfill", nargs=2, type=int, metavar=("START", "END"),
                        help="Backfill da anno START a END")

    args = parser.parse_args()

    if args.backfill:
        backfill(args.backfill[0], args.backfill[1],
                 region=args.region, profession=args.profession,
                 event_type=args.type, fetch_details=args.details,
                 db_path=args.db)
    else:
        batch_scrape(
            year=args.year, region=args.region,
            profession=args.profession, event_type=args.type,
            fetch_details=args.details, db_path=args.db
        )
