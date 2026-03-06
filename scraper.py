"""
ECMRadar — ECM Intelligence Radar (v2.0)
=========================================
Scraper per ape.agenas.it calibrato sull'HTML reale.

Struttura del sito:
- URL base: https://ape.agenas.it/Tools/Eventi.aspx
- URL dettaglio: https://ape.agenas.it/Tools/DettaglioEvento.aspx (solo via PostBack)
- Form prefix: ctl00$cphMain$Eventi1$
- Risultati: div.lista con span indicizzati (non tabelle)
- Paginazione: DataPager1 con input submit
- Dettaglio: click su ibDettaglioEvento → PostBack → DettaglioEvento.aspx
- Dettaglio campi: span con ID cphMain_DettaglioEvento_*

Autore: Alessandro Pietrelli
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import re
import time
import json
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── CONFIG ────────────────────────────────────────────────────────────────────
BASE_URL = "https://ape.agenas.it/Tools/Eventi.aspx"
DETAIL_URL = "https://ape.agenas.it/Tools/DettaglioEvento.aspx"
DB_PATH = Path("ecm_database.db")
DELAY_BETWEEN_REQUESTS = 2.0
MAX_PAGES_PER_SEARCH = 50
REQUEST_TIMEOUT = 30

# Prefisso form ASP.NET (reale)
FORM_PREFIX = "ctl00$cphMain$Eventi1$"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("ecmradar")

# ── DROPDOWN VALUES (reali) ───────────────────────────────────────────────────
PROFESSIONS = {
    "Medico Chirurgo": "1", "Odontoiatra": "2", "Farmacista": "3",
    "Veterinario": "4", "Psicologo": "5", "Biologo": "6",
    "Chimico": "7", "Fisico": "8", "Assistente Sanitario": "9",
    "Dietista": "10", "Educatore Professionale": "11",
    "Fisioterapista": "12", "Igienista Dentale": "13",
    "Infermiere": "14", "Infermiere Pediatrico": "15",
    "Logopedista": "16", "Ostetrica/O": "18",
    "Podologo": "19", "Tecnico Audiometrista": "20",
    "Tecnico Audioprotesista": "21",
    "Tecnico Sanitario Di Radiologia Medica": "27",
    "Tecnico Sanitario Laboratorio Biomedico": "28",
    "Tecnico Della Prevenzione": "23",
    "Tecnico Della Riabilitazione Psichiatrica": "24",
    "Tecnico Di Neurofisiopatologia": "25",
    "Tecnico Ortopedico": "26",
    "Terapista Occupazionale": "30",
    "Tutte Le Professioni": "99",
}

REGIONS = {
    "Piemonte": "010", "Valle D'aosta": "020", "Lombardia": "030",
    "Provincia Autonoma Bolzano": "041", "Provincia Autonoma Trento": "042",
    "Veneto": "050", "Friuli-Venezia Giulia": "060", "Liguria": "070",
    "Emilia-Romagna": "080", "Toscana": "090", "Umbria": "100",
    "Marche": "110", "Lazio": "120", "Abruzzo": "130", "Molise": "140",
    "Campania": "150", "Puglia": "160", "Basilicata": "170",
    "Calabria": "180", "Sicilia": "190", "Sardegna": "200",
}

EVENT_TYPES = {"FAD": "1", "FSC": "2", "RES": "3", "Blended": "4"}


# ── DATA MODEL ────────────────────────────────────────────────────────────────
@dataclass
class ECMEvent:
    event_id: Optional[str] = None
    provider_id: Optional[str] = None
    provider_name: Optional[str] = None
    title: Optional[str] = None
    event_type: Optional[str] = None
    profession: Optional[str] = None
    discipline: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    credits: Optional[float] = None
    cost: Optional[float] = None
    hours: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    objective: Optional[str] = None
    max_participants: Optional[int] = None
    detail_url: Optional[str] = None
    scraped_at: Optional[str] = None
    # Campi dettaglio
    sponsors: list = field(default_factory=list)
    speakers: list = field(default_factory=list)  # list of dict
    responsible_name: Optional[str] = None
    description: Optional[str] = None
    segreteria_email: Optional[str] = None
    segreteria_tel: Optional[str] = None
    # Indice nella lista risultati (per PostBack)
    _result_index: Optional[int] = None


# ── ASP.NET SESSION ───────────────────────────────────────────────────────────
class ASPNetSession:
    """Gestisce sessione ASP.NET con ViewState e PostBack"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self._asp_fields = {}
        self._form_defaults = {}
        # Accetta cookie policy automaticamente
        # Il sito usa jQuery $.cookie("ok_cookie", "ok_cookieSetting")
        self.session.cookies.set("ok_cookie", "ok_cookieSetting", domain="ape.agenas.it")

    def _extract_asp_fields(self, soup: BeautifulSoup):
        """Estrae ViewState, EventValidation, ecc."""
        self._asp_fields = {}
        for name in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
                      "__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS"]:
            tag = soup.find("input", {"name": name})
            if tag:
                self._asp_fields[name] = tag.get("value", "")

    def _capture_all_form_defaults(self, soup: BeautifulSoup):
        """Cattura TUTTI i valori di default del form (hidden + select + text).
        
        ASP.NET WebForms è molto sensibile: se manca un campo nel POST,
        il server può ignorare la richiesta. Catturiamo tutto dalla pagina
        iniziale e lo usiamo come base per ogni POST successivo.
        """
        self._form_defaults = {}
        for tag in soup.find_all(["input", "select"]):
            name = tag.get("name", "")
            if not name or name.startswith("__"):
                continue
            if tag.name == "select":
                # Prendi il valore selezionato o il primo option
                selected = tag.find("option", selected=True)
                if selected:
                    self._form_defaults[name] = selected.get("value", "")
                else:
                    first_opt = tag.find("option")
                    if first_opt:
                        self._form_defaults[name] = first_opt.get("value", "")
            elif tag.get("type") in ("text", "hidden"):
                self._form_defaults[name] = tag.get("value", "")
            # Skip submit/image/checkbox (vanno inviati esplicitamente)

    def _base_form(self) -> dict:
        """Campi ASP.NET base + TUTTI i default del form per ogni POST"""
        data = dict(self._form_defaults)  # tutti i default catturati dalla pagina
        data.update(self._asp_fields)     # ViewState, EventValidation, ecc.
        return data

    def get_page(self, url: str = BASE_URL) -> BeautifulSoup:
        """GET iniziale: ottiene ViewState e cattura tutti i campi form"""
        log.info(f"GET {url}")
        resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        self._extract_asp_fields(soup)
        self._capture_all_form_defaults(soup)
        return soup

    def post(self, form_data: dict, url: str = BASE_URL) -> BeautifulSoup:
        """POST con ViewState"""
        data = self._base_form()
        data.update(form_data)
        resp = self.session.post(url, data=data, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        self._extract_asp_fields(soup)
        return soup

    def search(self, title: str = "", profession: str = "", region: str = "",
               event_type: str = "", date_from: str = "", date_to: str = "",
               provider_name: str = "", objective: str = "",
               event_id: str = "", provider_id: str = "") -> BeautifulSoup:
        """Esegue una ricerca compilando il form.
        
        CRITICO: il server ASP.NET richiede TUTTI i campi del form,
        inclusi hidden fields e dropdown con valori di default.
        """
        P = FORM_PREFIX  # shorthand

        form = {
            # ── Hidden fields obbligatori ──
            "ctl00$hfRicercaAVanzata": "False",
            "ctl00$hfProviderAvanzata": "False",
            "ctl00$hfRicercaAvanzata1": "False",
            "ctl00$hfProviderAvanzata1": "False",
            f"{P}hidCerca": "",
            f"{P}hidprezzo": "0",
            f"{P}hfCrediti": "0",
            "ctl00$txtsearch": "",

            # ── Campi testo ──
            f"{P}tbDenominazioneProvider": provider_name,
            f"{P}tbTitoloEvento": title,
            f"{P}tbIDEvento": event_id,
            f"{P}tbIDProvider": provider_id,
            f"{P}tbDataInizio": date_from,
            f"{P}tbDataFine": date_to,

            # ── Dropdown (default = "non selezionato") ──
            f"{P}ddlProfessione": PROFESSIONS.get(profession, profession) if profession else "-1",
            f"{P}ddlDisciplina": "",
            f"{P}ddlRegioni": REGIONS.get(region, region) if region else "-1",
            f"{P}ddlTipologiaEvento": EVENT_TYPES.get(event_type, event_type) if event_type else "0",
            f"{P}ddlObiettivoFormativo": objective if objective else "-1",
            f"{P}ddlProvince": "",
            f"{P}ddlComune": "",
            f"{P}ddlNazione": "-1",

            # ── Bottone Cerca ──
            f"{P}btnCerca": "Cerca",
        }

        log.info(f"POST ricerca: title='{title}' prof='{profession}' "
                 f"region='{region}' type='{event_type}' "
                 f"dates='{date_from}'-'{date_to}'")
        return self.post(form)

    def navigate_page(self, page_number: int) -> BeautifulSoup:
        """Naviga alla pagina N dei risultati.

        La paginazione usa input submit con pattern:
        ctl00$cphMain$Eventi1$DataPager1$ctl01$ctl{NN}
        dove NN è l'indice 0-based del bottone pagina (01=pag2, 02=pag3, etc.)
        """
        # Il bottone per pagina N ha indice (N-2) nel gruppo ctl01
        # Pagina 2 → ctl01, Pagina 3 → ctl02, ...
        btn_index = page_number - 1  # 0-based
        btn_name = f"{FORM_PREFIX}DataPager1$ctl01$ctl{btn_index:02d}"

        form = {btn_name: str(page_number)}
        log.info(f"Navigazione pagina {page_number} ({btn_name})")
        return self.post(form)

    def click_detail(self, result_index: int) -> BeautifulSoup:
        """Clicca il bottone 'Dettaglio Evento' per il risultato N.

        Il bottone è un input type=image con PostBack:
        ctl00$cphMain$Eventi1$ResultTable$ctrl{N}$ibDettaglioEvento
        
        Per input type=image, il browser invia anche le coordinate .x e .y
        """
        target = f"ctl00$cphMain$Eventi1$ResultTable$ctrl{result_index}$ibDettaglioEvento"
        form = {
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": "",
            # Coordinate click (necessarie per input type=image)
            f"{target}.x": "10",
            f"{target}.y": "10",
        }
        log.info(f"Click dettaglio risultato #{result_index}")
        return self.post(form)

    def click_back_to_results(self) -> BeautifulSoup:
        """Torna dalla pagina dettaglio alla lista risultati.

        Usa il link 'Indietro': __doPostBack('ctl00$cphMain$DettaglioEvento$ibIndietro','')
        """
        form = {
            "__EVENTTARGET": "ctl00$cphMain$DettaglioEvento$ibIndietro",
            "__EVENTARGUMENT": "",
        }
        log.info("Click Indietro → torna ai risultati")
        return self.post(form, url=DETAIL_URL)


# ── PARSER ────────────────────────────────────────────────────────────────────
class ECMParser:
    """Parser calibrato sull'HTML reale di AGENAS"""

    @staticmethod
    def parse_search_results(soup: BeautifulSoup) -> list[ECMEvent]:
        """Parsa i risultati dalla lista div.lista"""
        events = []
        items = soup.find_all("div", class_="lista")

        if not items:
            # Diagnostic: log what div classes exist to spot HTML structure changes
            all_divs = soup.find_all("div", class_=True)
            classes_found = set()
            for d in all_divs:
                for c in d.get("class", []):
                    classes_found.add(c)
            log.warning(f"Nessun div.lista trovato. Classi div presenti: {sorted(classes_found)[:30]}")
            # Also check if there's an error or no-results message
            body_text = soup.get_text(" ", strip=True)[:500]
            log.warning(f"Testo pagina (primi 500 char): {body_text}")

        for idx, item in enumerate(items):
            event = ECMEvent(scraped_at=datetime.now().isoformat(), _result_index=idx)

            # Titolo (span nel div.headerLista)
            header = item.find("div", class_="headerLista")
            if header:
                title_span = header.find("span", id=re.compile(r"lbTitoloEvento"))
                if title_span:
                    event.title = title_span.get_text(strip=True)

            # Dettagli (div.DettaglioInformazioni con span indicizzati)
            detail = item.find("div", class_="DettaglioInformazioni")
            if not detail:
                if event.title:
                    events.append(event)
                continue

            # Provider name
            prov_span = detail.find("span", class_="TestoNomeProvider")
            if prov_span:
                event.provider_name = prov_span.get_text(strip=True)

            # Campi con pattern ID: lbValore* contiene il valore, lbl* è la label
            span_map = {}
            for span in detail.find_all("span", id=True):
                sid = span.get("id", "")
                text = span.get_text(strip=True)
                # Estrai la parte significativa dell'ID
                # es: cphMain_Eventi1_ResultTable_lbValoreEvento_0 → ValoreEvento
                match = re.search(r'_lb(Valore\w+)_\d+$', sid)
                if match:
                    span_map[match.group(1)] = text
                match2 = re.search(r'_lb(\w+)_\d+$', sid)
                if match2:
                    span_map[match2.group(1)] = text

            # Mappa i valori
            event.event_id = span_map.get("ValoreEvento", "")
            event.start_date = span_map.get("VAloreDataInizio", span_map.get("ValoreDataInizio", ""))
            event.end_date = span_map.get("VAloreDataFine", span_map.get("ValoreDataFine", ""))
            event.event_type = span_map.get("ValoreTipoEvento", "")
            event.profession = span_map.get("ValoreProfessioni", "")
            event.segreteria_email = span_map.get("ValoreEmail", "")
            event.segreteria_tel = span_map.get("ValoreTelefono", "")

            # Crediti
            cred_text = span_map.get("ValoreCrediti", "")
            if cred_text:
                try:
                    event.credits = float(cred_text.replace(",", "."))
                except ValueError:
                    pass

            # Costo
            cost_text = span_map.get("ValoreCosto", "")
            if cost_text:
                try:
                    cost_clean = re.sub(r'[^\d,.]', '', cost_text)
                    event.cost = float(cost_clean.replace(",", ".")) if cost_clean else 0.0
                except ValueError:
                    pass

            # Ore
            hours_text = span_map.get("ValoreOre", "")
            if hours_text:
                try:
                    event.hours = float(hours_text.replace(",", "."))
                except ValueError:
                    pass

            if event.event_id or event.title:
                events.append(event)

        log.info(f"Trovati {len(events)} eventi nella pagina")
        return events

    @staticmethod
    def get_result_count(soup: BeautifulSoup) -> Optional[int]:
        """Conta i risultati totali dal testo 'la ricerca ha prodotto N Risultati'"""
        panel = soup.find(id=re.compile(r"pnlTitoloRicerca", re.I))
        if panel:
            text = panel.get_text()
            match = re.search(r'(\d+)\s*Risultat', text)
            if match:
                return int(match.group(1))
        # Fallback
        text = soup.get_text()
        match = re.search(r'ha prodotto\s*(\d+)\s*Risultat', text)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def get_total_pages(soup: BeautifulSoup, per_page: int = 10) -> int:
        """Calcola il numero totale di pagine"""
        total = ECMParser.get_result_count(soup)
        if total:
            return (total + per_page - 1) // per_page
        # Conta i bottoni paginazione
        pager = soup.find(id=re.compile(r"pnlPaginazione", re.I))
        if pager:
            buttons = pager.find_all("input", {"type": "submit"})
            if buttons:
                return max(int(b.get("value", "1")) for b in buttons)
        return 1

    @staticmethod
    def get_available_pages(soup: BeautifulSoup) -> list[int]:
        """Restituisce le pagine disponibili nella paginazione corrente"""
        pages = []
        pager = soup.find(id=re.compile(r"pnlPaginazione", re.I))
        if pager:
            for btn in pager.find_all("input", {"type": "submit"}):
                try:
                    pages.append(int(btn.get("value", "0")))
                except ValueError:
                    pass
        return sorted(pages)

    @staticmethod
    def parse_event_detail(soup: BeautifulSoup, event: ECMEvent) -> ECMEvent:
        """Parsa la pagina DettaglioEvento.aspx.

        Tutti i campi sono in span con ID tipo:
        cphMain_DettaglioEvento_lbl{Campo}Valore
        """
        PREFIX = "cphMain_DettaglioEvento_"

        def get_span(suffix: str) -> str:
            """Helper per estrarre testo da span con ID"""
            span = soup.find("span", id=f"{PREFIX}{suffix}")
            return span.get_text(strip=True) if span else ""

        # ── INFO BASE ────────────────────────────────────────────
        event.event_id = event.event_id or get_span("lbNumeroEventoValore")
        event.title = event.title or get_span("lblTitoloEventoValore")
        event.provider_id = event.provider_id or get_span("lbIDProviderValore")
        event.provider_name = event.provider_name or get_span("lbDenominazioneProviderValore")

        # Date
        event.start_date = event.start_date or get_span("lblDataIniValore")
        event.end_date = event.end_date or get_span("lblDataEndiValore")
        # Anche date FAD
        if not event.start_date:
            event.start_date = get_span("lblDataInizioFADValore")
        if not event.end_date:
            event.end_date = get_span("lblDataFineFADValore")

        # ── PARTECIPANTI / CREDITI / COSTO ───────────────────────
        part_text = get_span("lblNumeroPartecipantiValore")
        if part_text:
            try:
                event.max_participants = int(re.sub(r'[^\d]', '', part_text))
            except ValueError:
                pass

        credits_text = get_span("lblCreditiValore")
        if credits_text and not event.credits:
            try:
                event.credits = float(credits_text.replace(",", "."))
            except ValueError:
                pass

        cost_text = get_span("lblQuotaPartecipazioneValore")
        if cost_text and event.cost is None:
            try:
                cost_clean = re.sub(r'[^\d,.]', '', cost_text)
                event.cost = float(cost_clean.replace(",", ".")) if cost_clean else 0.0
            except ValueError:
                pass

        # ── OBIETTIVO FORMATIVO ──────────────────────────────────
        event.objective = event.objective or get_span("lblValoreObiettivoFormativo")

        # ── TIPOLOGIA EVENTO ─────────────────────────────────────
        if not event.event_type:
            fad = get_span("lblTipologiaFADValore")
            if fad:
                event.event_type = "FAD"
            # Cerca anche RES/FSC
            for suffix in ["lblTipologiaRESValore", "lblTipologiaFSCValore"]:
                val = get_span(suffix)
                if val:
                    event.event_type = suffix.replace("lblTipologia", "").replace("Valore", "")

        # ── SEGRETERIA ───────────────────────────────────────────
        event.segreteria_email = event.segreteria_email or get_span("lblSegreOrgEmailValore")
        event.segreteria_tel = event.segreteria_tel or get_span("lblSegreOrgTelefonoValore")

        # ── DOCENTI E RESPONSABILI (tabelle reali) ──────────────
        # Le tabelle persone hanno header: Cognome | Nome | Qualifica
        # Distinguiamo docenti da responsabili in base alla label che precede
        person_tables = []
        for table in soup.find_all("table"):
            first_row = table.find("tr")
            if first_row:
                headers = [c.get_text(strip=True) for c in first_row.find_all(["td", "th"])]
                if "Cognome" in headers and "Nome" in headers:
                    person_tables.append(table)

        # Determina ruolo in base alla posizione relativa ai label
        docenti_label = soup.find("span", id=f"{PREFIX}lblDocenti")
        resp_label = soup.find("span", id=f"{PREFIX}lblResponsabiliScientifici")

        for table in person_tables:
            # Controlla quale label è più vicina prima della tabella
            role = "docente"
            table_pos = str(soup).find(str(table))
            
            if docenti_label and resp_label:
                doc_pos = str(soup).find(str(docenti_label))
                resp_pos = str(soup).find(str(resp_label))
                
                # La tabella appartiene alla label più vicina che la precede
                if resp_pos < table_pos and (doc_pos > table_pos or resp_pos > doc_pos):
                    role = "responsabile_scientifico"

            persons = ECMParser._parse_person_table(table, role=role)
            for p in persons:
                if role == "responsabile_scientifico":
                    event.responsible_name = event.responsible_name or p["full_name"]
                if not any(s["full_name"] == p["full_name"] for s in event.speakers):
                    event.speakers.append(p)

        # ── SPONSOR (tabella reale) ──────────────────────────────
        # La tabella sponsor ha header "Nome Sponsor" — cerchiamola per header
        for table in soup.find_all("table"):
            first_row = table.find("tr")
            if first_row:
                header_text = first_row.get_text(strip=True)
                if "Nome Sponsor" in header_text or "Sponsor" == header_text.strip():
                    for row in table.find_all("tr")[1:]:
                        cells = row.find_all("td")
                        if cells:
                            name = cells[0].get_text(strip=True)
                            if name and name.upper() != "NOME SPONSOR" and name not in event.sponsors:
                                event.sponsors.append(name)

        # ── REGIONE / CITTÀ ──────────────────────────────────────
        # Cerchiamo nei div di dettaglio del modulo RES/FAD
        for span in soup.find_all("span", id=re.compile(r"lblRegione|lblComune", re.I)):
            sid = span.get("id", "")
            text = span.get_text(strip=True)
            if "Valore" in sid:
                if "Regione" in sid and not event.region:
                    event.region = text
                elif "Comune" in sid and not event.city:
                    event.city = text

        return event

    @staticmethod
    def _parse_person_table(table: BeautifulSoup, role: str = "docente") -> list[dict]:
        """Parsa una tabella persone (Cognome | Nome | Qualifica)"""
        persons = []
        rows = table.find_all("tr")
        if len(rows) < 2:
            return persons

        for row in rows[1:]:  # skip header
            cells = row.find_all("td")
            if len(cells) >= 2:
                cognome = cells[0].get_text(strip=True)
                nome = cells[1].get_text(strip=True)
                qualifica = cells[2].get_text(strip=True) if len(cells) > 2 else ""

                if cognome and nome and cognome.upper() != "COGNOME":
                    persons.append({
                        "full_name": f"{cognome} {nome}".title(),
                        "codice_fiscale": "",
                        "qualifica": qualifica,
                        "role": role,
                    })
        return persons


# ── DATABASE ──────────────────────────────────────────────────────────────────
class ECMDatabase:
    """SQLite con schema relazionale"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS providers (
            provider_id TEXT PRIMARY KEY, name TEXT NOT NULL,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT (datetime('now')),
            total_events INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, provider_id TEXT, title TEXT,
            event_type TEXT, profession TEXT, discipline TEXT,
            region TEXT, city TEXT, credits REAL, cost REAL, hours REAL,
            start_date TEXT, end_date TEXT, objective TEXT,
            max_participants INTEGER, responsible TEXT, description TEXT,
            segreteria_email TEXT, segreteria_tel TEXT,
            detail_url TEXT, scraped_at TEXT,
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
        );
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL, sponsor_name TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            UNIQUE(event_id, sponsor_name)
        );
        CREATE TABLE IF NOT EXISTS speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL, speaker_name TEXT NOT NULL,
            role TEXT, codice_fiscale TEXT, qualifica TEXT,
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            UNIQUE(event_id, speaker_name)
        );
        CREATE TABLE IF NOT EXISTS event_professions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL, profession TEXT NOT NULL, discipline TEXT,
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            UNIQUE(event_id, profession, discipline)
        );
        CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_params TEXT, events_found INTEGER, pages_scraped INTEGER,
            started_at TEXT, finished_at TEXT, status TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_provider ON events(provider_id);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_region ON events(region);
        CREATE INDEX IF NOT EXISTS idx_events_dates ON events(start_date);
        CREATE INDEX IF NOT EXISTS idx_sponsors_name ON sponsors(sponsor_name);
        CREATE INDEX IF NOT EXISTS idx_speakers_name ON speakers(speaker_name);
        """)
        self.conn.commit()
        log.info(f"Database inizializzato: {self.db_path}")

    def upsert_event(self, event: ECMEvent):
        """Inserisce o aggiorna un evento con tutti i dati relazionali"""
        # Provider
        if event.provider_id or event.provider_name:
            pid = event.provider_id or f"unk_{hash(event.provider_name) % 100000}"
            self.conn.execute("""
                INSERT INTO providers (provider_id, name, last_seen, total_events)
                VALUES (?, ?, datetime('now'), 1)
                ON CONFLICT(provider_id) DO UPDATE SET
                    name = COALESCE(NULLIF(excluded.name, ''), name),
                    last_seen = datetime('now'),
                    total_events = total_events + 1
            """, (pid, event.provider_name or "N/A"))
            event.provider_id = pid

        # Evento
        self.conn.execute("""
            INSERT INTO events (event_id, provider_id, title, event_type, profession,
                discipline, region, city, credits, cost, hours, start_date, end_date,
                objective, max_participants, responsible, description,
                segreteria_email, segreteria_tel, detail_url, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_id) DO UPDATE SET
                title = COALESCE(NULLIF(excluded.title,''), title),
                provider_id = COALESCE(NULLIF(excluded.provider_id,''), provider_id),
                event_type = COALESCE(NULLIF(excluded.event_type,''), event_type),
                credits = COALESCE(excluded.credits, credits),
                cost = COALESCE(excluded.cost, cost),
                hours = COALESCE(excluded.hours, hours),
                region = COALESCE(NULLIF(excluded.region,''), region),
                city = COALESCE(NULLIF(excluded.city,''), city),
                objective = COALESCE(NULLIF(excluded.objective,''), objective),
                max_participants = COALESCE(excluded.max_participants, max_participants),
                responsible = COALESCE(NULLIF(excluded.responsible,''), responsible),
                segreteria_email = COALESCE(NULLIF(excluded.segreteria_email,''), segreteria_email),
                segreteria_tel = COALESCE(NULLIF(excluded.segreteria_tel,''), segreteria_tel),
                scraped_at = excluded.scraped_at
        """, (
            event.event_id, event.provider_id, event.title, event.event_type,
            event.profession, event.discipline, event.region, event.city,
            event.credits, event.cost, event.hours, event.start_date, event.end_date,
            event.objective, event.max_participants, event.responsible_name,
            event.description, event.segreteria_email, event.segreteria_tel,
            event.detail_url, event.scraped_at
        ))

        # Sponsor
        for sponsor in event.sponsors:
            self.conn.execute(
                "INSERT OR IGNORE INTO sponsors (event_id, sponsor_name) VALUES (?,?)",
                (event.event_id, sponsor))

        # Speaker
        for s in event.speakers:
            if isinstance(s, dict):
                self.conn.execute("""
                    INSERT OR IGNORE INTO speakers (event_id, speaker_name, role, codice_fiscale, qualifica)
                    VALUES (?,?,?,?,?)
                """, (event.event_id, s.get("full_name",""), s.get("role","docente"),
                      s.get("codice_fiscale",""), s.get("qualifica","")))
            else:
                self.conn.execute(
                    "INSERT OR IGNORE INTO speakers (event_id, speaker_name, role) VALUES (?,?,'docente')",
                    (event.event_id, s))

        self.conn.commit()

    def get_stats(self) -> dict:
        stats = {}
        for table in ["events", "providers", "sponsors", "speakers"]:
            stats[table] = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return stats

    def close(self):
        self.conn.close()


# ── SCRAPER ORCHESTRATOR ──────────────────────────────────────────────────────
class ECMScraper:
    """Orchestratore scraping con gestione sessione e navigazione"""

    def __init__(self, db: ECMDatabase):
        self.asp = ASPNetSession()
        self.parser = ECMParser()
        self.db = db

    def scrape_search(self, search_params: dict, fetch_details: bool = False) -> list[ECMEvent]:
        """Esegue ricerca completa con paginazione e opzionalmente dettagli"""
        all_events = []
        log_entry = {
            "search_params": json.dumps(search_params),
            "started_at": datetime.now().isoformat(),
            "events_found": 0, "pages_scraped": 0, "status": "running"
        }

        try:
            # 1. Pagina iniziale (ottieni ViewState)
            self.asp.get_page()
            time.sleep(DELAY_BETWEEN_REQUESTS)

            # 2. Ricerca
            result_soup = self.asp.search(**search_params)
            time.sleep(DELAY_BETWEEN_REQUESTS)

            # 3. Prima pagina risultati
            total_count = self.parser.get_result_count(result_soup)
            total_pages = self.parser.get_total_pages(result_soup)
            log.info(f"Risultati dal server: {total_count}, Pagine stimate: {total_pages}")
            if total_count == 0 or total_count is None:
                log.warning("Il server ha risposto con 0 risultati: controlla i parametri di ricerca "
                            "(codice regione, nome campo form, valori dropdown)")
                # Save debug HTML if total is 0
                debug_file = Path("debug_response.html")
                debug_file.write_text(str(result_soup), encoding="utf-8")
                log.warning(f"HTML risposta salvato in: {debug_file.resolve()}")
            events = self.parser.parse_search_results(result_soup)
            all_events.extend(events)
            log_entry["pages_scraped"] = 1

            # 4. Dettagli per eventi della prima pagina
            if fetch_details and events:
                self._fetch_details_for_page(events, result_soup)

            # 5. Pagine successive
            for page in range(2, min(total_pages + 1, MAX_PAGES_PER_SEARCH)):
                time.sleep(DELAY_BETWEEN_REQUESTS)
                try:
                    page_soup = self.asp.navigate_page(page)
                    events = self.parser.parse_search_results(page_soup)
                    if not events:
                        log.info("Pagina vuota, stop")
                        break
                    all_events.extend(events)
                    log_entry["pages_scraped"] += 1

                    if fetch_details:
                        self._fetch_details_for_page(events, page_soup)

                except Exception as e:
                    log.error(f"Errore pagina {page}: {e}")
                    time.sleep(5)
                    continue

            # 6. Salva tutto nel DB
            for event in all_events:
                self.db.upsert_event(event)

            log_entry["events_found"] = len(all_events)
            log_entry["status"] = "success"

        except Exception as e:
            log.error(f"Errore scraping: {e}")
            log_entry["status"] = f"error: {e}"
            # Salva comunque gli eventi raccolti
            for event in all_events:
                self.db.upsert_event(event)
            raise

        finally:
            log_entry["finished_at"] = datetime.now().isoformat()
            self.db.conn.execute("""
                INSERT INTO scrape_log (search_params, events_found, pages_scraped,
                    started_at, finished_at, status)
                VALUES (?,?,?,?,?,?)
            """, (log_entry["search_params"], log_entry["events_found"],
                  log_entry["pages_scraped"], log_entry["started_at"],
                  log_entry["finished_at"], log_entry["status"]))
            self.db.conn.commit()

        log.info(f"Completato: {len(all_events)} eventi in {log_entry['pages_scraped']} pagine")
        return all_events

    def _fetch_details_for_page(self, events: list[ECMEvent], current_soup: BeautifulSoup):
        """Carica i dettagli per ogni evento della pagina corrente.

        Meccanismo: click ibDettaglioEvento → DettaglioEvento.aspx → parse → Indietro
        """
        for event in events:
            if event._result_index is None:
                continue
            try:
                time.sleep(DELAY_BETWEEN_REQUESTS)
                detail_soup = self.asp.click_detail(event._result_index)
                self.parser.parse_event_detail(detail_soup, event)
                log.info(f"  Dettaglio {event.event_id}: "
                         f"{len(event.speakers)} speaker, {len(event.sponsors)} sponsor")

                # Torna alla lista risultati
                time.sleep(DELAY_BETWEEN_REQUESTS)
                self.asp.click_back_to_results()

            except Exception as e:
                log.warning(f"  Errore dettaglio {event.event_id}: {e}")
                # Prova a recuperare tornando alla pagina iniziale
                try:
                    self.asp.get_page()
                except Exception:
                    pass


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ECMRadar Scraper")
    parser.add_argument("--title", "-k", default="", help="Keyword nel titolo")
    parser.add_argument("--profession", "-p", default="", help="Professione")
    parser.add_argument("--region", "-r", default="", help="Regione")
    parser.add_argument("--type", "-t", default="", help="FAD, RES, FSC, Blended")
    parser.add_argument("--date-from", default="", help="gg/mm/aaaa")
    parser.add_argument("--date-to", default="", help="gg/mm/aaaa")
    parser.add_argument("--provider", default="", help="Nome provider")
    parser.add_argument("--objective", default="", help="Obiettivo formativo (numero)")
    parser.add_argument("--event-id", default="", help="ID specifico evento")
    parser.add_argument("--provider-id", default="", help="ID specifico provider")
    parser.add_argument("--details", action="store_true", help="Carica pagine dettaglio")
    parser.add_argument("--db", default="ecm_database.db", help="Path database")
    parser.add_argument("--save-html", metavar="FILE", default="", help="Salva l'HTML della risposta di ricerca in FILE per debug")

    args = parser.parse_args()

    db = ECMDatabase(Path(args.db))
    scraper = ECMScraper(db)

    search_params = {
        "title": args.title,
        "profession": args.profession,
        "region": args.region,
        "event_type": args.type,
        "date_from": args.date_from,
        "date_to": args.date_to,
        "provider_name": args.provider,
        "objective": args.objective,
        "event_id": args.event_id,
        "provider_id": args.provider_id,
    }
    search_params = {k: v for k, v in search_params.items() if v}
    if args.save_html:
        # Modalità debug: GET + POST ricerca e salva l'HTML senza scraping completo
        scraper.asp.get_page()
        result_soup = scraper.asp.search(**search_params)
        Path(args.save_html).write_text(str(result_soup), encoding="utf-8")
        count = ECMParser.get_result_count(result_soup)
        items = result_soup.find_all("div", class_="lista")
        print(f"Risultati server: {count}, div.lista trovati: {len(items)}")
        print(f"HTML salvato in: {Path(args.save_html).resolve()}")
        db.close()
        raise SystemExit(0)

    events = scraper.scrape_search(search_params, fetch_details=args.details)
    stats = db.get_stats()
    print(f"\n{'='*50}")
    print(f"DB Stats: {json.dumps(stats, indent=2)}")
    db.close()
