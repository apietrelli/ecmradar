# 📡 ECMRadar

**Radar sulla formazione medica italiana.** Pipeline di intelligence per scraping, arricchimento e analisi degli eventi ECM dal portale [ape.agenas.it](https://ape.agenas.it).

## Cosa fa

Scarica tutti gli eventi formativi ECM pubblicati da AGENAS e li salva in un database SQLite locale, arricchendoli con:

- **Provider** — chi organizza l'evento
- **Sponsor** — chi finanzia (aziende pharma, device, etc.)
- **Speaker/Docenti** — nomi, codici fiscali, qualifiche
- **Responsabili scientifici**
- **Crediti, costi, regioni, obiettivi formativi**

Query analitiche pronte:

| Analisi | Comando |
|---|---|
| Top provider per volume | `profiler.py top-providers` |
| Top sponsor | `profiler.py top-sponsors` |
| KOL per area terapeutica | `profiler.py kol oncologia` |
| Chi parla per chi (speaker↔sponsor) | `profiler.py speaker-sponsors` |
| Network di un KOL | `profiler.py speaker "Rossi Mario"` |
| Footprint aziendale | `profiler.py pharma "Alfasigma"` |
| Matrice sponsor×provider | `profiler.py matrix` |
| Ricerca full-text | `profiler.py search "MICI"` |

## Architettura

```
ecmradar/
├── scraper.py          # Core: ASP.NET session, parser HTML, database SQLite
├── batch_scrape.py     # Scraping massivo per anno (splitta in trimestri)
├── enrich.py           # Enrichment incrementale (solo eventi senza dettagli)
├── profiler.py         # 15+ query analitiche + CLI interattiva
├── export.py           # Export CSV/Excel (7 fogli/tabelle)
├── inspect_fields.py   # Calibrazione campi ASP.NET (una tantum)
├── test_pipeline.py    # Test end-to-end con dati simulati
├── ECMRadar_Colab.ipynb # Notebook Google Colab pronto
├── requirements.txt
└── README.md
```

## Quick Start — Google Colab (consigliato)

Non serve installare nulla. Tutto gira nel cloud di Google.

1. Carica questo repo su GitHub
2. Vai su [colab.research.google.com](https://colab.research.google.com)
3. **File → Apri notebook → GitHub** → incolla URL repo
4. Seleziona `ECMRadar_Colab.ipynb`
5. Esegui le celle in ordine

Il DB e gli export finiscono su Google Drive (`/MyDrive/ECMRadar/`).

## Quick Start — Locale

```bash
pip install -r requirements.txt

# 1. Calibra i campi ASP.NET (una volta sola)
python inspect_fields.py --save

# 2. Test singola ricerca
python scraper.py --region Lombardia --date-from 01/01/2025 --date-to 31/03/2025

# 3. Dump massivo (senza dettagli = veloce)
python batch_scrape.py --year 2025

# 4. Arricchisci con speaker/sponsor (a blocchi)
python enrich.py --limit 500
python enrich.py --stats

# 5. Export
python export.py --format both

# 6. Analisi
python profiler.py top-sponsors
python profiler.py kol gastroenterologia
```

## Workflow per dump completo

```bash
# Fase 1: lista eventi (veloce, ~1-2 ore/anno)
python batch_scrape.py --backfill 2022 2025

# Fase 2: arricchimento incrementale (a sessioni)
python enrich.py --limit 500    # ~17 min a blocco, riprende automaticamente
python enrich.py --stats        # monitora progresso

# Fase 3: export per analisi offline
python export.py --format both
```

## Schema Database

```
providers (provider_id PK, name)
    ↓
events (event_id PK, provider_id FK, title, event_type, credits,
        cost, region, city, start_date, objective, max_participants)
    ↓
sponsors (event_id FK, sponsor_name)
speakers (event_id FK, speaker_name, role, codice_fiscale, qualifica)
event_professions (event_id FK, profession, discipline)
scrape_log (search_params, events_found, status)
```

## Export

`export.py` genera 7 tabelle/fogli:

| Tabella | Contenuto |
|---|---|
| **events** | Tutti gli eventi con nome provider |
| **providers** | Provider aggregati (n_eventi, sponsor, speaker, regioni) |
| **sponsors** | Sponsor aggregati per volume |
| **speakers** | Speaker aggregati (KOL ranking) |
| **speaker_sponsor_links** | Chi parla per chi |
| **sponsor_provider_matrix** | Chi finanzia chi |
| **flat_view** | Vista denormalizzata (1 riga = evento×speaker×sponsor) |

Formati: CSV (separatore `;`) e/o Excel con fogli multipli, filtri e freeze pane.

## Rate Limiting

| Parametro | Valore | Nota |
|---|---|---|
| Delay tra richieste | 2s | Configurabile con `--delay` |
| Delay tra ricerche | 3s | In batch_scrape |
| Backoff su errore | 10s | Automatico |
| Max pagine per ricerca | 50 | Safety limit |
| Timeout richiesta | 30s | |

## Limitazioni

- **No dati partecipanti/discenti**: i nomi dei medici iscritti non sono pubblici (serve SPID/myECM)
- **Dati pubblici disponibili**: eventi, provider, sponsor, docenti/relatori, responsabili scientifici
- **Limite 180 giorni per ricerca**: `batch_scrape.py` splitta automaticamente in trimestri
- **ASP.NET stateful**: non parallelizzabile, una sessione alla volta

## Dipendenze

- Python 3.10+
- requests, beautifulsoup4, lxml, tabulate, openpyxl

## Licenza

[![License: CC BY-NC-SA 4.0](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc-sa/4.0/)

Questo progetto è rilasciato sotto licenza [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
Puoi usarlo, modificarlo e condividerlo per scopi non commerciali, citando l'autore.
Per licenze commerciali, contatta l'autore.

I dati ECM sono pubblici su ape.agenas.it.
