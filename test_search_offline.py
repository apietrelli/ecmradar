"""
Test offline della ricerca keyword (senza rete).
=================================================
Verifica con HTML di fixture che:
1. la cattura del form estrae campi, dropdown e bottoni
2. la risoluzione per suffisso trova i campi anche se il prefisso ASP.NET cambia
3. il bottone Cerca viene individuato e inviato secondo il suo tipo
4. il parser estrae correttamente i risultati (div.lista)
5. la paginazione trova il bottone reale della pagina N

Uso:
    python test_search_offline.py
"""

from bs4 import BeautifulSoup

from scraper import ASPNetSession, ECMParser, FORM_PREFIX

# ── FIXTURE: pagina form ricerca (struttura reale AGENAS) ─────────────────────
FORM_PAGE = """
<html><body>
<form action="./Eventi.aspx" method="post">
<input type="hidden" name="__VIEWSTATE" value="dDwtMTIzNDU2Nzg5Ozs+" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="ABCD1234" />
<input type="hidden" name="__EVENTVALIDATION" value="dDwxMjM0NTY3ODk7Oz4=" />
<input type="hidden" name="ctl00$hfRicercaAVanzata" value="False" />
<input type="hidden" name="ctl00$cphMain$Eventi1$hidCerca" value="" />
<input type="hidden" name="ctl00$cphMain$Eventi1$hidprezzo" value="0" />
<input type="text" name="ctl00$cphMain$Eventi1$tbTitoloEvento" id="cphMain_Eventi1_tbTitoloEvento" value="" />
<input type="text" name="ctl00$cphMain$Eventi1$tbDenominazioneProvider" value="" />
<input type="text" name="ctl00$cphMain$Eventi1$tbIDEvento" value="" />
<input type="text" name="ctl00$cphMain$Eventi1$tbDataInizio" value="" />
<input type="text" name="ctl00$cphMain$Eventi1$tbDataFine" value="" />
<select name="ctl00$cphMain$Eventi1$ddlProfessione">
  <option value="-1" selected="selected">Seleziona...</option>
  <option value="1">Medico Chirurgo</option>
</select>
<select name="ctl00$cphMain$Eventi1$ddlRegioni">
  <option value="-1" selected="selected">Seleziona...</option>
  <option value="030">Lombardia</option>
</select>
<select name="ctl00$cphMain$Eventi1$ddlTipologiaEvento">
  <option value="0" selected="selected">Tutte</option>
  <option value="1">FAD</option>
</select>
<input type="submit" name="ctl00$cphMain$Eventi1$btnCerca" value="Cerca" id="cphMain_Eventi1_btnCerca" />
</form>
</body></html>
"""

# Stessa pagina ma con prefisso ASP.NET diverso (simula cambio struttura sito)
FORM_PAGE_NEW_PREFIX = FORM_PAGE.replace("ctl00$cphMain$Eventi1$", "ctl00$NuovoMain$Ricerca2$")

# ── FIXTURE: pagina risultati ─────────────────────────────────────────────────
RESULTS_PAGE = """
<html><body>
<form action="./Eventi.aspx" method="post">
<input type="hidden" name="__VIEWSTATE" value="risultati123" />
<input type="hidden" name="__EVENTVALIDATION" value="ev456" />
<input type="text" name="ctl00$cphMain$Eventi1$tbTitoloEvento" value="diabete" />
<div id="cphMain_Eventi1_pnlTitoloRicerca">la ricerca ha prodotto 23 Risultati</div>

<div class="lista">
  <div class="headerLista">
    <span id="cphMain_Eventi1_ResultTable_lbTitoloEvento_0">Gestione del diabete tipo 2</span>
  </div>
  <div class="DettaglioInformazioni">
    <span class="TestoNomeProvider">Provider Alfa SRL</span>
    <span id="cphMain_Eventi1_ResultTable_lbValoreEvento_0">123456</span>
    <span id="cphMain_Eventi1_ResultTable_lbValoreTipoEvento_0">FAD</span>
    <span id="cphMain_Eventi1_ResultTable_lbValoreCrediti_0">10,5</span>
    <span id="cphMain_Eventi1_ResultTable_lbValoreCosto_0">Gratuito 0,00 &euro;</span>
    <span id="cphMain_Eventi1_ResultTable_lbVAloreDataInizio_0">01/09/2026</span>
    <span id="cphMain_Eventi1_ResultTable_lbVAloreDataFine_0">31/12/2026</span>
  </div>
</div>

<div class="lista">
  <div class="headerLista">
    <span id="cphMain_Eventi1_ResultTable_lbTitoloEvento_1">Diabete e nutrizione</span>
  </div>
  <div class="DettaglioInformazioni">
    <span class="TestoNomeProvider">Provider Beta SPA</span>
    <span id="cphMain_Eventi1_ResultTable_lbValoreEvento_1">654321</span>
    <span id="cphMain_Eventi1_ResultTable_lbValoreTipoEvento_1">RES</span>
    <span id="cphMain_Eventi1_ResultTable_lbValoreCrediti_1">8</span>
  </div>
</div>

<div id="cphMain_Eventi1_pnlPaginazione">
  <input type="submit" name="ctl00$cphMain$Eventi1$DataPager1$ctl01$ctl00" value="1" />
  <input type="submit" name="ctl00$cphMain$Eventi1$DataPager1$ctl01$ctl01" value="2" />
  <input type="submit" name="ctl00$cphMain$Eventi1$DataPager1$ctl01$ctl02" value="3" />
</div>
</form>
</body></html>
"""


def make_session(html: str) -> ASPNetSession:
    """Crea una sessione con form già catturato dalla fixture (senza rete)"""
    asp = ASPNetSession()
    soup = BeautifulSoup(html, "html.parser")
    asp._extract_asp_fields(soup)
    asp._capture_all_form_defaults(soup)
    asp.last_soup = soup
    return asp


def test_form_capture():
    asp = make_session(FORM_PAGE)
    assert asp._asp_fields["__VIEWSTATE"] == "dDwtMTIzNDU2Nzg5Ozs+"
    assert f"{FORM_PREFIX}tbTitoloEvento" in asp._form_defaults
    assert asp._form_defaults[f"{FORM_PREFIX}ddlProfessione"] == "-1"
    # Il bottone NON deve finire nei default (il browser invia solo il bottone cliccato)
    assert f"{FORM_PREFIX}btnCerca" not in asp._form_defaults
    assert f"{FORM_PREFIX}btnCerca" in asp._buttons
    print("✓ test_form_capture")


def test_field_resolution_standard_prefix():
    asp = make_session(FORM_PAGE)
    assert asp._resolve_field("tbTitoloEvento", "FALLBACK") == f"{FORM_PREFIX}tbTitoloEvento"
    btn_name, btn_kind = asp._find_search_button()
    assert btn_name == f"{FORM_PREFIX}btnCerca"
    assert btn_kind == "submit"
    print("✓ test_field_resolution_standard_prefix")


def test_field_resolution_changed_prefix():
    """Se AGENAS cambia il prefisso, i campi vengono trovati lo stesso"""
    asp = make_session(FORM_PAGE_NEW_PREFIX)
    assert asp._resolve_field("tbTitoloEvento", "FALLBACK") == \
        "ctl00$NuovoMain$Ricerca2$tbTitoloEvento"
    btn_name, btn_kind = asp._find_search_button()
    assert btn_name == "ctl00$NuovoMain$Ricerca2$btnCerca"
    assert btn_kind == "submit"
    print("✓ test_field_resolution_changed_prefix")


def test_parse_results():
    soup = BeautifulSoup(RESULTS_PAGE, "html.parser")
    assert ECMParser.get_result_count(soup) == 23
    assert ECMParser.get_total_pages(soup) == 3  # 23 risultati / 10 per pagina

    events = ECMParser.parse_search_results(soup)
    assert len(events) == 2

    ev = events[0]
    assert ev.title == "Gestione del diabete tipo 2"
    assert ev.event_id == "123456"
    assert ev.provider_name == "Provider Alfa SRL"
    assert ev.event_type == "FAD"
    assert ev.credits == 10.5
    assert ev.cost == 0.0
    assert ev.start_date == "01/09/2026"
    assert ev._result_index == 0

    assert events[1].event_id == "654321"
    assert events[1].credits == 8.0
    print("✓ test_parse_results")


def test_pagination_button_lookup():
    """navigate_page deve trovare il bottone reale con value == numero pagina"""
    asp = make_session(RESULTS_PAGE)
    captured = {}

    def fake_post(form, url=None):
        captured.update(form)
        return asp.last_soup
    asp.post = fake_post

    asp.navigate_page(2)
    assert captured == {"ctl00$cphMain$Eventi1$DataPager1$ctl01$ctl01": "2"}
    print("✓ test_pagination_button_lookup")


def test_results_as_dicts():
    """I risultati devono essere convertibili in dict usabili (come search_events)"""
    from dataclasses import asdict
    soup = BeautifulSoup(RESULTS_PAGE, "html.parser")
    events = ECMParser.parse_search_results(soup)
    dicts = []
    for ev in events:
        d = asdict(ev)
        d.pop("_result_index", None)
        dicts.append(d)
    assert dicts[0]["title"] == "Gestione del diabete tipo 2"
    assert dicts[0]["credits"] == 10.5
    import json
    json.dumps(dicts)  # serializzabile
    print("✓ test_results_as_dicts")


if __name__ == "__main__":
    test_form_capture()
    test_field_resolution_standard_prefix()
    test_field_resolution_changed_prefix()
    test_parse_results()
    test_pagination_button_lookup()
    test_results_as_dicts()
    print("\nTutti i test offline superati ✓")
