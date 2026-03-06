"""
ECM Profiler - Query analitiche per profiling provider e sponsor
================================================================
Libreria di query pronte per analizzare il DB ECM.
Usabile standalone o come modulo importabile.
"""

import sqlite3
import json
from pathlib import Path
from tabulate import tabulate


class ECMProfiler:
    """Query analitiche sul database ECM"""

    def __init__(self, db_path: str = "ecm_database.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Esegue query e restituisce lista di dict"""
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def print_table(self, data: list[dict], title: str = ""):
        """Stampa risultati in formato tabella"""
        if not data:
            print(f"  (nessun risultato)")
            return
        if title:
            print(f"\n{'═'*60}")
            print(f"  {title}")
            print(f"{'═'*60}")
        print(tabulate(data, headers="keys", tablefmt="rounded_outline"))
        print(f"  [{len(data)} righe]")

    # ══════════════════════════════════════════════════════════════════════
    # PROFILING PROVIDER
    # ══════════════════════════════════════════════════════════════════════

    def top_providers(self, limit: int = 20) -> list[dict]:
        """Top provider per numero di eventi"""
        return self.query("""
            SELECT
                p.provider_id,
                p.name AS provider,
                COUNT(e.event_id) AS num_eventi,
                ROUND(AVG(e.credits), 1) AS crediti_medi,
                ROUND(AVG(e.cost), 0) AS costo_medio,
                COUNT(DISTINCT e.region) AS regioni_coperte,
                GROUP_CONCAT(DISTINCT e.event_type) AS tipologie
            FROM providers p
            JOIN events e ON p.provider_id = e.provider_id
            GROUP BY p.provider_id
            ORDER BY num_eventi DESC
            LIMIT ?
        """, (limit,))

    def provider_profile(self, provider_id: str) -> dict:
        """Profilo completo di un singolo provider"""
        # Info base
        base = self.query("""
            SELECT * FROM providers WHERE provider_id = ?
        """, (provider_id,))

        # Eventi per tipo
        by_type = self.query("""
            SELECT event_type, COUNT(*) as n,
                   ROUND(AVG(credits), 1) as avg_credits,
                   ROUND(SUM(cost), 0) as total_cost
            FROM events WHERE provider_id = ?
            GROUP BY event_type
        """, (provider_id,))

        # Distribuzione regionale
        by_region = self.query("""
            SELECT region, COUNT(*) as n
            FROM events WHERE provider_id = ?
            GROUP BY region ORDER BY n DESC
        """, (provider_id,))

        # Obiettivi formativi preferiti
        by_objective = self.query("""
            SELECT objective, COUNT(*) as n
            FROM events WHERE provider_id = ? AND objective IS NOT NULL
            GROUP BY objective ORDER BY n DESC LIMIT 5
        """, (provider_id,))

        # Sponsor associati
        sponsors = self.query("""
            SELECT s.sponsor_name, COUNT(*) as n_events
            FROM sponsors s
            JOIN events e ON s.event_id = e.event_id
            WHERE e.provider_id = ?
            GROUP BY s.sponsor_name ORDER BY n_events DESC
        """, (provider_id,))

        # Speaker ricorrenti
        speakers = self.query("""
            SELECT sp.speaker_name, sp.role, COUNT(*) as n_events
            FROM speakers sp
            JOIN events e ON sp.event_id = e.event_id
            WHERE e.provider_id = ?
            GROUP BY sp.speaker_name ORDER BY n_events DESC LIMIT 10
        """, (provider_id,))

        return {
            "base": base[0] if base else {},
            "by_type": by_type,
            "by_region": by_region,
            "by_objective": by_objective,
            "sponsors": sponsors,
            "top_speakers": speakers
        }

    # ══════════════════════════════════════════════════════════════════════
    # PROFILING SPONSOR / AZIENDE
    # ══════════════════════════════════════════════════════════════════════

    def top_sponsors(self, limit: int = 20) -> list[dict]:
        """Top sponsor per numero di eventi finanziati"""
        return self.query("""
            SELECT
                s.sponsor_name AS sponsor,
                COUNT(DISTINCT s.event_id) AS num_eventi,
                COUNT(DISTINCT e.provider_id) AS num_provider,
                GROUP_CONCAT(DISTINCT e.event_type) AS tipologie,
                GROUP_CONCAT(DISTINCT e.region) AS regioni,
                ROUND(AVG(e.credits), 1) AS crediti_medi
            FROM sponsors s
            JOIN events e ON s.event_id = e.event_id
            GROUP BY s.sponsor_name
            ORDER BY num_eventi DESC
            LIMIT ?
        """, (limit,))

    def sponsor_profile(self, sponsor_name: str) -> dict:
        """Profilo dettagliato di uno sponsor"""
        events = self.query("""
            SELECT e.event_id, e.title, e.event_type, e.region,
                   e.start_date, e.credits, p.name as provider
            FROM sponsors s
            JOIN events e ON s.event_id = e.event_id
            LEFT JOIN providers p ON e.provider_id = p.provider_id
            WHERE s.sponsor_name LIKE ?
            ORDER BY e.start_date DESC
        """, (f"%{sponsor_name}%",))

        # Con quali provider collabora
        providers = self.query("""
            SELECT p.name as provider, COUNT(*) as n_events
            FROM sponsors s
            JOIN events e ON s.event_id = e.event_id
            JOIN providers p ON e.provider_id = p.provider_id
            WHERE s.sponsor_name LIKE ?
            GROUP BY p.provider_id ORDER BY n_events DESC
        """, (f"%{sponsor_name}%",))

        # Aree terapeutiche (da obiettivi + titoli)
        objectives = self.query("""
            SELECT e.objective, COUNT(*) as n
            FROM sponsors s
            JOIN events e ON s.event_id = e.event_id
            WHERE s.sponsor_name LIKE ? AND e.objective IS NOT NULL
            GROUP BY e.objective ORDER BY n DESC
        """, (f"%{sponsor_name}%",))

        return {
            "events": events,
            "providers": providers,
            "objectives": objectives,
            "total_events": len(events)
        }

    # ══════════════════════════════════════════════════════════════════════
    # PROFILING SPEAKER / KOL
    # ══════════════════════════════════════════════════════════════════════

    def top_speakers(self, limit: int = 20) -> list[dict]:
        """Top KOL per partecipazione a eventi"""
        return self.query("""
            SELECT
                sp.speaker_name AS speaker,
                sp.role,
                COUNT(DISTINCT sp.event_id) AS num_eventi,
                COUNT(DISTINCT e.provider_id) AS num_provider,
                GROUP_CONCAT(DISTINCT e.event_type) AS tipologie,
                GROUP_CONCAT(DISTINCT e.region) AS regioni
            FROM speakers sp
            JOIN events e ON sp.event_id = e.event_id
            GROUP BY sp.speaker_name
            ORDER BY num_eventi DESC
            LIMIT ?
        """, (limit,))

    def speaker_network(self, speaker_name: str) -> dict:
        """Rete relazionale di uno speaker: con chi collabora"""
        # Co-speaker: chi appare negli stessi eventi
        co_speakers = self.query("""
            SELECT sp2.speaker_name, sp2.role, sp2.qualifica,
                   COUNT(DISTINCT sp2.event_id) as shared_events
            FROM speakers sp1
            JOIN speakers sp2 ON sp1.event_id = sp2.event_id
                AND sp1.speaker_name != sp2.speaker_name
            WHERE sp1.speaker_name LIKE ?
            GROUP BY sp2.speaker_name
            ORDER BY shared_events DESC LIMIT 15
        """, (f"%{speaker_name}%",))

        # Provider per cui lavora
        providers = self.query("""
            SELECT p.name as provider, COUNT(*) as n
            FROM speakers sp
            JOIN events e ON sp.event_id = e.event_id
            JOIN providers p ON e.provider_id = p.provider_id
            WHERE sp.speaker_name LIKE ?
            GROUP BY p.provider_id ORDER BY n DESC
        """, (f"%{speaker_name}%",))

        # Sponsor associati (via eventi)
        sponsors = self.query("""
            SELECT s.sponsor_name, COUNT(*) as n
            FROM speakers sp
            JOIN events e ON sp.event_id = e.event_id
            JOIN sponsors s ON e.event_id = s.event_id
            WHERE sp.speaker_name LIKE ?
            GROUP BY s.sponsor_name ORDER BY n DESC
        """, (f"%{speaker_name}%",))

        # Aree tematiche (obiettivi formativi)
        topics = self.query("""
            SELECT e.objective, COUNT(*) as n
            FROM speakers sp
            JOIN events e ON sp.event_id = e.event_id
            WHERE sp.speaker_name LIKE ? AND e.objective IS NOT NULL
            GROUP BY e.objective ORDER BY n DESC LIMIT 5
        """, (f"%{speaker_name}%",))

        # Timeline attività
        timeline = self.query("""
            SELECT e.start_date, e.title, e.region, p.name as provider
            FROM speakers sp
            JOIN events e ON sp.event_id = e.event_id
            LEFT JOIN providers p ON e.provider_id = p.provider_id
            WHERE sp.speaker_name LIKE ?
            ORDER BY e.start_date DESC LIMIT 20
        """, (f"%{speaker_name}%",))

        return {
            "co_speakers": co_speakers,
            "providers": providers,
            "sponsors": sponsors,
            "topics": topics,
            "recent_events": timeline
        }

    def kol_mapping(self, area_keyword: str = "", limit: int = 30) -> list[dict]:
        """KOL mapping: speaker più attivi, opzionalmente filtrati per area terapeutica.

        Perfetto per identificare i Key Opinion Leader in un'area specifica.
        """
        if area_keyword:
            return self.query("""
                SELECT
                    sp.speaker_name,
                    sp.qualifica,
                    COUNT(DISTINCT sp.event_id) AS n_eventi,
                    COUNT(DISTINCT e.provider_id) AS n_provider,
                    COUNT(DISTINCT s.sponsor_name) AS n_sponsor,
                    GROUP_CONCAT(DISTINCT sp.role) AS ruoli,
                    GROUP_CONCAT(DISTINCT e.region) AS regioni
                FROM speakers sp
                JOIN events e ON sp.event_id = e.event_id
                LEFT JOIN sponsors s ON e.event_id = s.event_id
                WHERE (e.title LIKE ? OR e.objective LIKE ? OR e.description LIKE ?)
                GROUP BY sp.speaker_name
                HAVING n_eventi >= 2
                ORDER BY n_eventi DESC
                LIMIT ?
            """, (f"%{area_keyword}%", f"%{area_keyword}%",
                  f"%{area_keyword}%", limit))
        else:
            return self.query("""
                SELECT
                    sp.speaker_name,
                    sp.qualifica,
                    COUNT(DISTINCT sp.event_id) AS n_eventi,
                    COUNT(DISTINCT e.provider_id) AS n_provider,
                    COUNT(DISTINCT s.sponsor_name) AS n_sponsor,
                    GROUP_CONCAT(DISTINCT sp.role) AS ruoli,
                    GROUP_CONCAT(DISTINCT e.region) AS regioni
                FROM speakers sp
                JOIN events e ON sp.event_id = e.event_id
                LEFT JOIN sponsors s ON e.event_id = s.event_id
                GROUP BY sp.speaker_name
                HAVING n_eventi >= 2
                ORDER BY n_eventi DESC
                LIMIT ?
            """, (limit,))

    def speaker_sponsor_links(self, limit: int = 30) -> list[dict]:
        """Mappa chi parla per chi: speaker ↔ sponsor.

        Fondamentale per capire i rapporti commerciali.
        """
        return self.query("""
            SELECT
                sp.speaker_name,
                s.sponsor_name,
                COUNT(DISTINCT e.event_id) AS n_events,
                GROUP_CONCAT(DISTINCT e.objective) AS topics,
                GROUP_CONCAT(DISTINCT e.region) AS regions
            FROM speakers sp
            JOIN events e ON sp.event_id = e.event_id
            JOIN sponsors s ON e.event_id = s.event_id
            GROUP BY sp.speaker_name, s.sponsor_name
            HAVING n_events >= 2
            ORDER BY n_events DESC
            LIMIT ?
        """, (limit,))

    def speakers_by_qualifica(self) -> list[dict]:
        """Distribuzione speaker per qualifica professionale"""
        return self.query("""
            SELECT qualifica, COUNT(DISTINCT speaker_name) as n_speakers,
                   COUNT(*) as n_partecipazioni
            FROM speakers
            WHERE qualifica IS NOT NULL AND qualifica != ''
            GROUP BY qualifica
            ORDER BY n_speakers DESC
        """)

    # ══════════════════════════════════════════════════════════════════════
    # ANALISI TRASVERSALI
    # ══════════════════════════════════════════════════════════════════════

    def events_by_region(self) -> list[dict]:
        """Distribuzione eventi per regione"""
        return self.query("""
            SELECT region, COUNT(*) as n_eventi,
                   ROUND(AVG(credits), 1) as crediti_medi,
                   COUNT(DISTINCT provider_id) as n_provider
            FROM events WHERE region IS NOT NULL
            GROUP BY region ORDER BY n_eventi DESC
        """)

    def events_by_type(self) -> list[dict]:
        """Distribuzione per tipologia"""
        return self.query("""
            SELECT event_type, COUNT(*) as n,
                   ROUND(AVG(credits), 1) as avg_credits,
                   ROUND(AVG(cost), 0) as avg_cost
            FROM events WHERE event_type IS NOT NULL
            GROUP BY event_type ORDER BY n DESC
        """)

    def events_timeline(self, granularity: str = "month") -> list[dict]:
        """Timeline degli eventi (per mese o anno)"""
        if granularity == "year":
            date_expr = "SUBSTR(start_date, -4)"
        else:
            date_expr = "SUBSTR(start_date, 4, 7)"  # MM/YYYY

        return self.query(f"""
            SELECT {date_expr} as period, COUNT(*) as n_eventi,
                   COUNT(DISTINCT provider_id) as n_provider
            FROM events WHERE start_date IS NOT NULL
            GROUP BY period ORDER BY period
        """)

    def sponsor_provider_matrix(self) -> list[dict]:
        """Matrice sponsor × provider (chi finanzia chi)"""
        return self.query("""
            SELECT
                s.sponsor_name AS sponsor,
                p.name AS provider,
                COUNT(DISTINCT e.event_id) AS n_events,
                GROUP_CONCAT(DISTINCT e.event_type) AS types
            FROM sponsors s
            JOIN events e ON s.event_id = e.event_id
            JOIN providers p ON e.provider_id = p.provider_id
            GROUP BY s.sponsor_name, p.provider_id
            ORDER BY n_events DESC
            LIMIT 50
        """)

    def pharma_footprint(self, company_name: str) -> dict:
        """Footprint formativo di un'azienda pharma (come sponsor + provider)"""
        as_sponsor = self.sponsor_profile(company_name)
        as_provider = self.query("""
            SELECT * FROM providers WHERE name LIKE ?
        """, (f"%{company_name}%",))

        provider_events = []
        for p in as_provider:
            provider_events.extend(self.query("""
                SELECT e.*, p.name as provider_name
                FROM events e
                JOIN providers p ON e.provider_id = p.provider_id
                WHERE p.provider_id = ?
            """, (p["provider_id"],)))

        return {
            "as_sponsor": as_sponsor,
            "as_provider": as_provider,
            "provider_events": provider_events,
            "total_sponsored": as_sponsor["total_events"],
            "total_organized": len(provider_events)
        }

    def search_events(self, keyword: str, limit: int = 50) -> list[dict]:
        """Ricerca full-text negli eventi"""
        return self.query("""
            SELECT e.event_id, e.title, e.event_type, e.region,
                   e.start_date, e.credits, p.name as provider
            FROM events e
            LEFT JOIN providers p ON e.provider_id = p.provider_id
            WHERE e.title LIKE ? OR e.description LIKE ? OR e.objective LIKE ?
            ORDER BY e.start_date DESC
            LIMIT ?
        """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit))

    def close(self):
        self.conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    profiler = ECMProfiler()

    commands = {
        "top-providers": lambda: profiler.print_table(
            profiler.top_providers(), "TOP PROVIDER PER EVENTI"),
        "top-sponsors": lambda: profiler.print_table(
            profiler.top_sponsors(), "TOP SPONSOR PER EVENTI"),
        "top-speakers": lambda: profiler.print_table(
            profiler.top_speakers(), "TOP KOL PER PARTECIPAZIONE"),
        "by-region": lambda: profiler.print_table(
            profiler.events_by_region(), "DISTRIBUZIONE PER REGIONE"),
        "by-type": lambda: profiler.print_table(
            profiler.events_by_type(), "DISTRIBUZIONE PER TIPOLOGIA"),
        "matrix": lambda: profiler.print_table(
            profiler.sponsor_provider_matrix(), "MATRICE SPONSOR × PROVIDER"),
        "speaker-sponsors": lambda: profiler.print_table(
            profiler.speaker_sponsor_links(), "LEGAMI SPEAKER ↔ SPONSOR"),
        "speakers-qualifica": lambda: profiler.print_table(
            profiler.speakers_by_qualifica(), "SPEAKER PER QUALIFICA"),
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Uso: python profiler.py <comando>")
        print(f"\nComandi rapidi: {', '.join(commands.keys())}")
        print("\nComandi con parametro:")
        print("  python profiler.py provider <ID>")
        print("  python profiler.py sponsor <NOME>")
        print("  python profiler.py speaker <NOME>")
        print("  python profiler.py pharma <AZIENDA>")
        print("  python profiler.py search <KEYWORD>")
        print("  python profiler.py kol <AREA_TERAPEUTICA>    # KOL mapping per area")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd in commands:
        commands[cmd]()
    elif cmd == "provider" and len(sys.argv) > 2:
        profile = profiler.provider_profile(sys.argv[2])
        print(json.dumps(profile, indent=2, ensure_ascii=False, default=str))
    elif cmd == "sponsor" and len(sys.argv) > 2:
        profile = profiler.sponsor_profile(" ".join(sys.argv[2:]))
        print(json.dumps(profile, indent=2, ensure_ascii=False, default=str))
    elif cmd == "speaker" and len(sys.argv) > 2:
        network = profiler.speaker_network(" ".join(sys.argv[2:]))
        print(json.dumps(network, indent=2, ensure_ascii=False, default=str))
    elif cmd == "pharma" and len(sys.argv) > 2:
        fp = profiler.pharma_footprint(" ".join(sys.argv[2:]))
        print(json.dumps(fp, indent=2, ensure_ascii=False, default=str))
    elif cmd == "search" and len(sys.argv) > 2:
        results = profiler.search_events(" ".join(sys.argv[2:]))
        profiler.print_table(results, f"RICERCA: {' '.join(sys.argv[2:])}")
    elif cmd == "kol" and len(sys.argv) > 2:
        results = profiler.kol_mapping(area_keyword=" ".join(sys.argv[2:]))
        profiler.print_table(results, f"KOL MAPPING: {' '.join(sys.argv[2:])}")
    elif cmd == "kol":
        results = profiler.kol_mapping()
        profiler.print_table(results, "KOL MAPPING (tutte le aree)")
    else:
        print(f"Comando sconosciuto: {cmd}")

    profiler.close()
