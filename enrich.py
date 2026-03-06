"""
ECMRadar Enrichment Incrementale (v2)
======================================
Arricchisce SOLO gli eventi senza dettagli (speaker/sponsor).

Meccanica v2: la pagina dettaglio è accessibile SOLO via PostBack
dalla lista risultati. Quindi per arricchire:
1. Cerca per ID evento
2. Click "Dettaglio Evento" sul risultato
3. Parse la pagina dettaglio
4. Torna indietro

Uso:
    python enrich.py --stats
    python enrich.py --limit 500
    python enrich.py --year 2025 --limit 200
"""

import argparse
import time
import logging
import sqlite3
from pathlib import Path

from scraper import (ASPNetSession, ECMParser, ECMDatabase, ECMEvent,
                     DELAY_BETWEEN_REQUESTS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ecmradar_enrich")


def get_events_to_enrich(db_path: str, limit: int = 0, offset: int = 0,
                          provider_id: str = "", year: int = 0) -> list[dict]:
    """Trova eventi senza speaker/sponsor"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    query = """
        SELECT e.event_id, e.title, e.provider_id, e.start_date
        FROM events e
        WHERE e.event_id NOT IN (SELECT DISTINCT event_id FROM speakers)
          AND e.event_id NOT IN (SELECT DISTINCT event_id FROM sponsors)
    """
    params = []
    if provider_id:
        query += " AND e.provider_id = ?"
        params.append(provider_id)
    if year:
        query += " AND (e.start_date LIKE ? OR e.start_date LIKE ?)"
        params.extend([f"%/{year}", f"{year}-%"])
    query += " ORDER BY e.start_date DESC"
    if limit > 0:
        query += f" LIMIT {limit} OFFSET {offset}"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_enrichment_stats(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    enriched = conn.execute("""
        SELECT COUNT(DISTINCT e.event_id) FROM events e
        WHERE e.event_id IN (SELECT DISTINCT event_id FROM speakers)
           OR e.event_id IN (SELECT DISTINCT event_id FROM sponsors)
    """).fetchone()[0]
    with_speakers = conn.execute("SELECT COUNT(DISTINCT event_id) FROM speakers").fetchone()[0]
    with_sponsors = conn.execute("SELECT COUNT(DISTINCT event_id) FROM sponsors").fetchone()[0]
    conn.close()
    return {
        "total_events": total, "with_speakers": with_speakers,
        "with_sponsors": with_sponsors, "enriched": enriched,
        "to_enrich": total - enriched,
        "pct_complete": round(enriched / total * 100, 1) if total > 0 else 0
    }


def enrich(db_path: str = "ecm_database.db", limit: int = 0, offset: int = 0,
           provider_id: str = "", year: int = 0, delay: float = DELAY_BETWEEN_REQUESTS):
    """Arricchimento incrementale via PostBack"""

    stats = get_enrichment_stats(db_path)
    log.info(f"DB: {stats['total_events']} totali, {stats['enriched']} arricchiti "
             f"({stats['pct_complete']}%), {stats['to_enrich']} da fare")

    if stats["to_enrich"] == 0:
        log.info("Tutti arricchiti!")
        return

    events_to_do = get_events_to_enrich(db_path, limit, offset, provider_id, year)
    log.info(f"Da arricchire questa sessione: {len(events_to_do)}")
    if not events_to_do:
        return

    est_min = len(events_to_do) * (delay * 3) / 60  # 3 requests per evento
    log.info(f"Tempo stimato: ~{est_min:.0f} min")

    asp = ASPNetSession()
    parser = ECMParser()
    db = ECMDatabase(Path(db_path))

    success = errors = empty = 0

    for i, evt in enumerate(events_to_do):
        eid = evt["event_id"]
        try:
            log.info(f"[{i+1}/{len(events_to_do)}] Evento {eid}: {evt.get('title','')[:50]}")

            # 1. Cerca per ID evento
            asp.get_page()
            time.sleep(delay)
            result_soup = asp.search(event_id=eid)
            time.sleep(delay)

            # 2. Parse risultati (dovrebbe esserci 1 solo risultato)
            results = parser.parse_search_results(result_soup)
            if not results:
                empty += 1
                log.info(f"  → Nessun risultato per ID {eid}")
                continue

            # 3. Click dettaglio sul primo risultato
            detail_soup = asp.click_detail(0)
            time.sleep(delay)

            # 4. Parse dettaglio
            event = ECMEvent(event_id=eid, provider_id=evt.get("provider_id"))
            parser.parse_event_detail(detail_soup, event)

            if event.speakers or event.sponsors:
                db.upsert_event(event)
                success += 1
                log.info(f"  → {len(event.speakers)} speaker, {len(event.sponsors)} sponsor")
            else:
                empty += 1
                log.info(f"  → Nessun dettaglio trovato")

        except KeyboardInterrupt:
            log.warning(f"\nInterrotto dopo {i} eventi")
            break
        except Exception as e:
            errors += 1
            log.warning(f"  ERRORE: {e}")
            if errors > 10 and errors > success:
                log.error("Troppi errori. Stop.")
                break

        time.sleep(delay)

    db.close()

    final = get_enrichment_stats(db_path)
    log.info(f"\n{'='*50}")
    log.info(f"COMPLETATO: {success} arricchiti, {empty} vuoti, {errors} errori")
    log.info(f"DB: {final['enriched']}/{final['total_events']} ({final['pct_complete']}%)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="ECMRadar Enrichment")
    p.add_argument("--db", default="ecm_database.db")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--provider", default="")
    p.add_argument("--year", type=int, default=0)
    p.add_argument("--delay", type=float, default=DELAY_BETWEEN_REQUESTS)
    p.add_argument("--stats", action="store_true")
    args = p.parse_args()

    if args.stats:
        s = get_enrichment_stats(args.db)
        print(f"\n{'═'*50}")
        print(f"  STATO ENRICHMENT — {args.db}")
        print(f"{'═'*50}")
        for k, v in s.items():
            label = k.replace("_", " ").title()
            print(f"  {label:20s} {v}")
        print(f"{'═'*50}")
    else:
        enrich(args.db, args.limit, args.offset, args.provider, args.year, args.delay)
