from playwright.sync_api import sync_playwright, expect, Error
from playwright._impl._errors import TimeoutError
from icalendar import Calendar, Event, vDatetime, vDate
from urllib.parse import quote
import sys
import re
import base64
from webbrowser import open as webbrowser_open
from time import sleep
from contextlib import nullcontext
from datetime import date, timedelta
import fire

USER = 'masdeu'
URL_TPD = "https://web01.uab.es:31501/pds/transparenciaPD/InicioTransparencia?entradaPublica=true&idioma=ca&pais=ES#"
URL_HORARIS = "https://web01.uab.es:31501/pds/consultaPublica/look%5Bconpub%5DInicioPubHora?entradaPublica=true&idiomaPais=ca.ES"  # <-- set the page URL where the original script runs
BROWSER_PATH = "/home/" + USER + "/.cache/ms-playwright/chromium_headless_shell-1200/chrome-headless-shell-linux64/chrome-headless-shell"  # <-- set the path to your Chromium browser executable

import sys

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def inicialitza_funcions(page, llista_assignatures):
    # Prepare the list of subjects
    txt = (''.join((f'crea_element("{a.codi}", "{a.centre}", "{a.periode}"),' for a in llista_assignatures))).rstrip(',')
    # Run the original logic: create elements, set #jsonBusquedaAsignaturas and submit the form
    page.evaluate("""
    () => {
        // recreate crea_element from test.js
        function crea_element(asignatura, centro, periode){
        var element1 = {asignatura: asignatura, centro: centro, periodo: periode,
            plan: "-1", estudio: "", indExamen: "true", grupo: "-1"};
        var key1 = String(jPubhora.crearHash(element1));
        var obj = {};
        obj[key1] = element1;
        return obj;
        }

        var dadesRR = Object.assign({},""" + txt + """
        );
        var jsonEl = document.querySelector("#jsonBusquedaAsignaturas");
        if (jsonEl) jsonEl.value = JSON.stringify(dadesRR);
        var form = document.querySelector("#formu_Edi_Asignatura");
        form.setAttribute("action", "look[conpub]MostrarPubHora?rnd=3428.0");
        form.submit();
        }
    """)

def descarrega_calendari_sia(page):
    # Start waiting for the download
    # Perform the action that initiates download
    page.evaluate("""
    (function(){jQuery.ajax({
                url: "/pds/control/[mtoGenerarICS]",
                type: "POST",
                data: {},
                dataType: "json",
                success: function(response) {
                    var icsBase64 = response.data.result;
                    
                    // Decodificar el base64 a un Blob
                    var byteCharacters = atob(icsBase64);  // Decodificamos el base64
                    var byteNumbers = new Array(byteCharacters.length);
                    for (var i = 0; i < byteCharacters.length; i++) {
                        byteNumbers[i] = byteCharacters.charCodeAt(i);
                    }
                    var byteArray = new Uint8Array(byteNumbers);
                    var blob = new Blob([byteArray], { type: 'text/calendar' });
                    document.blobData = blob.text();
            },
                error: function(jqXHR, textStatus, errorThrown) {
                    document.querySelector('#error-icalc').innerHTML = "Ha fallat la generació de l'arxiu.";
                    document.querySelector('#error-icalc').style.visibility = "";
                },
                complete: function() {
                    document.querySelector('.fc-downloadICSButton-button .fa').classList.remove('fa-spinner', 'fa-spin');
                    document.querySelector('.fc-downloadICSButton-button .fa').classList.add('fa-download');
                }
            });
        })();
    """)


def genera_assignatures(page):
    page.evaluate('''
        (function(){
        function collectCodes(){
            var tables = document.querySelectorAll('table.tablaFicha.taulaFitxa.centros');
            var result = {};
            var codeRe = /\\d{4,6}/; // capture code digits
            var fullCodeCellRe = /^\\s*(\\d{4,6})(?:\s*[-–:]\\s*(.*))?$/; // "101742 - Course Name"
            var slashPattern = '([A-Za-zÀ-ÿ0-9.\-]{1,20})\\s*\\/\\s*(\\d{1,3})';
            var noslashPattern = '([A-Za-zÀ-ÿ]{2,20})(\\d{1,3})';

            tables.forEach(function(tbl){
            // build header texts for heuristics
            var headerCells = [];
            var thead = tbl.querySelector('thead');
            if(thead){ thead.querySelectorAll('th').forEach(function(th){ headerCells.push((th.textContent||'').trim().toLowerCase()); }); }
            else { var first = tbl.querySelector('tr'); if(first) first.querySelectorAll('th,td').forEach(function(h){ headerCells.push((h.textContent||'').trim().toLowerCase()); }); }

            function findHeaderIndex(names){ for(var i=0;i<headerCells.length;i++){ for(var j=0;j<names.length;j++){ if(headerCells[i].indexOf(names[j].toLowerCase()) !== -1) return i; } } return -1; }

            var codiIdx = findHeaderIndex(['codi']);
            var grupIdx = findHeaderIndex(['grup']);

            var centre = (function(){ var h = tbl.querySelector('thead th a'); return h ? h.textContent.trim() : (tbl.getAttribute('data-cod-centro')||'Unknown centre'); })();
            if(!result[centre]) result[centre] = [];


            // track last seen code/name for rowspan behavior
            var lastCode = '';
            var lastName = '';

            var rows = tbl.querySelectorAll('tbody tr');
            rows.forEach(function(tr){
                var allTds = Array.prototype.slice.call(tr.querySelectorAll('td'));
                if(!allTds.length) return;

                // only first seven columns
                var tds = allTds.slice(0,7);

                // find code and rawName in this row (if present)
                var rawCode = '';
                var rawName = '';
                var codeCellIdx = -1;

                if(codiIdx >= 0 && tds[codiIdx]){
                var raw = (tds[codiIdx].textContent||'').trim();
                var mFull = raw.match(fullCodeCellRe);
                if(mFull){ rawCode = mFull[1]; rawName = (mFull[2]||'').trim(); codeCellIdx = codiIdx; }
                else { var m = raw.match(codeRe); if(m){ rawCode = m[0]; codeCellIdx = codiIdx; var rest = raw.replace(m[0],'').replace(/^\s*[-–:]?\s*/,'').trim(); if(rest) rawName = rest; } }
                }

                if(!rawCode){
                for(var i=0;i<tds.length;i++){
                    var txt = (tds[i].textContent||'').trim();
                    var mFull2 = txt.match(fullCodeCellRe);
                    if(mFull2){ rawCode = mFull2[1]; rawName = (mFull2[2]||'').trim(); codeCellIdx = i; break; }
                    var md = txt.match(codeRe);
                    if(md){ rawCode = md[0]; codeCellIdx = i; var after = txt.replace(md[0],'').replace(/^\s*[-–:]?\s*/,'').trim(); if(after) rawName = after; else if(i+1<tds.length) rawName = (tds[i+1].textContent||'').trim(); break; }
                }
                }

                // Handle rowspan: if no code found, reuse last seen; otherwise update last seen only when the code changes
                if(!rawCode){
                rawCode = lastCode;
                var idx_shift = 0;
                // keep rawName undefined here; we'll use lastName below
                } else {
                // rawCode found in this row
                var idx_shift = 2;
                if(rawCode !== lastCode){
                    // new code: compute a candidate name if rawName is empty
                    if(!rawName){
                    var candidate = '';
                    for(var k=0;k<tds.length;k++){
                        if(k === codeCellIdx) continue;
                        var txtk = (tds[k].textContent||'').trim(); if(!txtk) continue;
                        if(/[A-Za-zÀ-ÿ]/.test(txtk) && !new RegExp(slashPattern, 'i').test(txtk)){
                        if(txtk.length > candidate.length) candidate = txtk;
                        }
                    }
                    rawName = (candidate||'').trim();
                    }
                    lastCode = rawCode;
                    lastName = rawName || '';
                } else {
                    // same code as previous row: preserve lastName
                    rawName = lastName;
                }
                }

                if(!rawCode) return; // still none -- skip

                // final code/name values for this row
                var code = rawCode;
                var name = lastName || rawName || '';

                var period = tds[idx_shift + 3].textContent + '/' + tds[idx_shift + 4].textContent;
                var group = tds[idx_shift].textContent;
                
                // Extract digits from centre name
                var codicentre = centre.match(/\d+/)[0];
                result[centre].push([code, codicentre, name || '', group || '(no group)', period]);
            });
            });

            return result;
        }


        var data = collectCodes();

            var lines = [];
            Object.keys(data).forEach(function(name){
            data[name].forEach(function(p){
                // p = [code, codicentre, name, group, period]
                var code = ('"' + p[0] + '"') || '""';
                var codicentre = ('"' + p[1] + '"') || '""';
                var name = ('"' + p[2] + '"') || '""';
                var grp = ('"' + p[3] + '"') || '""';
                var period = ('"' + p[4] + '"') || '""';
                lines.push('(' + code + ', ' + codicentre + ', ' + grp + (period ? ', '+period : '') + (name ? ', '+name : '') + ')');
            });
            });
            document.llista_assignatures = '[' + lines.join(',') + ']';
        // For debugging: also expose a function to get the data object
        window.collectSiaCodesData = collectCodes;
        })();   
    ''')

class Assignatura():
    def __init__(self, codi, centre, grup, periode, nom):
        self.codi = str(codi)
        self.centre = str(centre)
        self.grup = str(grup)
        self.periode = str(periode)
        self.nom = str(nom)

    def nom_curt(self, max_len=30):
        n = self.nom
        if len(n) > max_len:
            n = n[:max_len-3] + '...'
        if len(n) < max_len:
            n = n + ' ' * (max_len - len(n))
        return n
    def __repr__(self):
        return f'{self.centre}/{self.codi}\t{self.nom_curt()}\t({self.periode}), {self.grup}'
    
    def color(self):
        base_colors = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
            "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
            "#bcbd22", "#17becf"
        ]
        index = (int(self.codi) + int(re.sub(r'\D', '', self.grup))) % len(base_colors)
        return base_colors[index]

    def __iter__(self):
        return iter((self.codi, self.centre, self.grup, self.periode, self.nom))
    
def t_abbrev(tipus_full, grup=None):
    tipus_abbrev = {
        'Teoria': 'TE',
        'Pràctiques d\'Aula': 'PAUL',
        'Pràctiques de Laboratori': 'PLAB',
        'Seminaris': 'SEM',
        'Examens': 'EX',
        'Examen': 'EX'
    }
    tipus = tipus_abbrev.get(tipus_full, tipus_full)
    if grup is None:
        return tipus
    else:
        return tipus + '/' + grup

def save_ics(calendar, outfile=None):
    # Save new calendar to file
        with open(outfile + '.ics', "wb") if outfile else nullcontext(sys.stdout) as f:
            f.write(calendar.to_ical())

def imprimeix_html(events, ics_string, outfile=None, standalone=None):
    ics_string = ics_string.decode('utf-8').replace('\r\n', '\n').strip()
    if standalone is None:
        standalone = not bool(outfile)
    with open(outfile + '.html', 'w') if outfile else nullcontext(sys.stdout) as f:
        if standalone:
            f.write('<html><head>\
            <link href="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.css" rel="stylesheet">\
            <script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/dist/index.global.js">\
            </script><script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.js">\
            </script><script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/locales-all.min.js"></script>\
            </head><body>\n')
                
        f.write('<button id="icaldownload" style="float: right; margin-bottom: 10px;">Descarrega iCal</button>\n')
        f.write('<div id="calendar"></div>\n')
        f.write('<script src="https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"></script>')
        f.write('<script>\n')
        # declare the events array in the global scope so other scripts can use it
        f.write('var $eventsJSON = [\n')
        for title, start, end, color, allday in events:
            if allday:
                f.write(f'      {{ title: "{title}", start: "{start}", end: "{end}", color: "{color}", allDay: "{allday}" }},\n')
            else:
                f.write(f'      {{ title: "{title}", start: "{start}", end: "{end}", color: "{color}" }},\n')
        f.write('    ];\n')
        # compute base64 for the ICS data so JS can atob() it
        b64_ics = base64.b64encode(ics_string).decode('ascii') if isinstance(ics_string, (bytes, bytearray)) else base64.b64encode(ics_string.encode('utf-8')).decode('ascii')
        f.write('''
            document.addEventListener("DOMContentLoaded", function() {
                var calendarEl = document.getElementById("calendar");
                // Decodificar el base64 a un Blob
                var icsBase64 = "''' + b64_ics + '''";
                var byteCharacters = atob(icsBase64);  // Decodificamos el base64
                var byteNumbers = new Array(byteCharacters.length);
                    for (var i = 0; i < byteCharacters.length; i++) {
                        byteNumbers[i] = byteCharacters.charCodeAt(i);
                    }
                    var byteArray = new Uint8Array(byteNumbers);
                    var blob = new Blob([byteArray], { type: 'text/calendar' });
                    document.icsBlob = blob;

                var calendar = new FullCalendar.Calendar(calendarEl, {
                    initialView: "listMonth",
                    events: $eventsJSON,
                    locale: "ca",
                    });
                calendar.render();
                });
                // Download iCal button onclick listener
                $("#icaldownload").on('click',function(){
                    var icsBlob = document.icsBlob;
                    if (icsBlob) {
                        var a = document.createElement("a");
                        a.href = URL.createObjectURL(icsBlob);
                        a.download = "calendar.ics";
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    }
                });</script>\n''')
        if standalone:
            f.write('</body></html>\n')
    if outfile:
        base_folder = sys.path[0]
        eprint('Visita la pàgina', 'file://' + base_folder + '/' + outfile + '.html per veure el calendari.')
        webbrowser_open('file://' + base_folder + '/' + outfile + '.html')

def get_assignatures(name):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=BROWSER_PATH)
        # navigate to page
        page = browser.new_page()
        while True:
            try:
                page.goto(URL_TPD)
                break
            except Error:
                sleep(1)
                page.goto(URL_TPD)        
        page.get_by_role('link', name='Pla Docent per departament').click(force=True)
        page.get_by_role('gridcell', name='Departament de matemàtiques').click(force=True)
        link = page.locator('[class="profesorDepartamento"]')
        try:
            for n in name.split(' '):
                n = n.strip().lower()
                link = link.filter(has_text=re.compile(n, re.IGNORECASE))
            link = link.first
            professor = link.inner_text()
            link.click(force=True)
            page.wait_for_load_state('networkidle')
        except TimeoutError:
            eprint(f"No s'ha trobat cap professor/a amb el nom '{name}'.")
            return None, []
            browser.close()
        genera_assignatures(page)
        while page.evaluate("document.llista_assignatures") is None:
            page.wait_for_timeout(100)
        llista_assignatures = [Assignatura(*o) for o in eval(page.evaluate('document.llista_assignatures'))]
        browser.close()
    return professor, llista_assignatures

def genera_calendari(llista_assignatures):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=BROWSER_PATH)
        # navigate to page
        page = browser.new_page()
        while True:
            try:
                page.goto(URL_HORARIS)
                break
            except Error:
                sleep(1)
                page.goto(URL_HORARIS)

        page.wait_for_load_state('networkidle')
        page.get_by_text("Cerca per assignatura").click()
        # Wait until the form is completely loaded
        expect(page.get_by_text("Veure Calendari")).to_be_visible(timeout=10000)

        inicialitza_funcions(page, llista_assignatures)

        expect(page.get_by_text("Tornar")).to_be_visible(timeout=10000)

        _ = descarrega_calendari_sia(page)

        # Expect blobData to be of length > 0
        while page.evaluate("document.blobData") is None:
            page.wait_for_timeout(100)

        # Convert document.blobData to something we can use
        calendar = Calendar.from_ical(page.evaluate("document.blobData"))
        newcal = Calendar()
        events_fullcalendar = []
        for event in calendar.events:
            data = str(event.get('SUMMARY'))
            lloc = 'Aula ' + str(event.get('LOCATION')).replace('Aula de docència', '').replace('d`', '').strip(' - ').strip()
            if lloc == 'Aula None':
                lloc = '** aula no assignada **'
            start = event.get('DTSTART')
            end = event.get('DTEND')
            # Extract code, name, group, type using regex: 100088 - Àlgebra Lineal Grup: 2 - Pràctiques d'Aula
            match = re.match(r'(\d+)\s*-\s*(.*?)\s*Grup:\s*(\d+)\s*-\s*(.*)', data)
            if match:
                codi, nom_assignatura, grup, tipus = match.groups()
                title = f'{codi} {nom_assignatura} ({t_abbrev(tipus)} - Grup {grup}) ➤ {lloc}'
                a = next((a for a in llista_assignatures if a.codi == codi and\
                         (a.grup == t_abbrev(tipus,grup) or t_abbrev(tipus) == 'EX')), None)
                if a is not None:
                    event = Event()
                    event['SUMMARY'] = data
                    event['LOCATION'] = lloc
                    event.add('dtstart', vDatetime(start.dt))
                    event.add('dtend', vDatetime(end.dt))  # make end date exclusive
                    newcal.add_component(event)
                    events_fullcalendar.append((title, str(start.dt), str(end.dt), a.color(), False))
            else: # Dies no lectius o similar
                # check whether start date is during weekend
                # TODO
                data = data.replace(' - ','')
                event = Event()
                event['SUMMARY'] = data
                # Set event to be all-day
                event.add('dtstart', vDate(start.dt))
                # End one day later
                event.add('dtend', vDate(end.dt+timedelta(days=1)))
                newcal.add_component(event) # Add non-lecture days to the ICS
                events_fullcalendar.append((data, str(start.dt), str(end.dt), '#808080', True))
        browser.close()
    return newcal, events_fullcalendar

def imprimeix_llista_assignatures(professor, llista_assignatures, html=True, outfile=None):
    if html:
        end = '<br>'
        sep = '<hr>'
        tab = '&nbsp;&nbsp;&nbsp;&nbsp;'
    else:
        end = ''
        sep = 30 * '-'
        tab = '\t'
    dict_assignatures = {(a.codi, a.centre, a.periode) : [] for a in llista_assignatures}
    for a in llista_assignatures:
        dict_assignatures[(a.codi, a.centre, a.periode)].append(a)
    with open(outfile + '.html', 'w') if outfile else nullcontext(sys.stdout) as f:
        f.write(f'Professor/a trobat: {professor}' + end + end)
        f.write(f'Centre/Codi{tab}Nom de l\'assignatura{tab}(Període), grups' + end)
        f.write(sep)
        for (codi, centre, periode), assignatures in dict_assignatures.items():
            linia = f'{centre}/{codi}\t{assignatures[0].nom_curt()}\t({periode}), '
            grups = ', '.join(sorted(set(a.grup for a in assignatures)))
            linia += grups
            f.write(linia.replace('\t', tab) + end)
        f.write(sep)

def fes_feed(name):
    professor, llista_assignatures = get_assignatures(name)
    calendar, _ = genera_calendari(llista_assignatures)
    # Generaate ICS feed directly to stdout
    sys.stdout.buffer.write(calendar.to_ical())
    return

def fes_web_calendari(name):
    professor, llista_assignatures = get_assignatures(name)

    if professor is None:
        print('No s\'ha trobat cap professor/a amb el nom especificat.\n')
        return
    # Write feed generating url in a box, with a copy to clipboard button
    name_safe = quote(name)

    feed_url = f'https://mat.uab.cat/~masdeu/teaching/misc/calendari_professor.php?nom={name_safe}&feed=true'

    with nullcontext(sys.stdout) as f:
        f.write('''
        <div style="margin-bottom: 10px;">
        URL del feed iCal:<br>
        <input type="text" id="feedUrl" value="''' + feed_url + '" readonly>'\
        + '''
        <button id="copyFeedUrl">Copia</button>
        </div>
        <script>
        document.getElementById("copyFeedUrl").addEventListener("click", function() {
            var copyText = document.getElementById("feedUrl");
            copyText.select();
            copyText.setSelectionRange(0, 99999); // For mobile devices
            document.execCommand("copy");
            alert("Copiat l'URL del feed: " + copyText.value);
        });
        </script>
        ''')

    calendar, events_fullcalendar = genera_calendari(llista_assignatures)
    imprimeix_llista_assignatures(professor, llista_assignatures, html=True, outfile=None)
    imprimeix_html(events_fullcalendar, calendar.to_ical(), None, standalone=False)
    return

def main(name, out_ics=True, out_html=True, outfile='calendari'):
    professor, llista_assignatures = get_assignatures(name)
    calendar, events_fullcalendar = genera_calendari(llista_assignatures)
    imprimeix_llista_assignatures(professor, llista_assignatures, html=False, outfile=None)
    if out_ics:
        save_ics(calendar, outfile)
    if out_html:
        imprimeix_html(events_fullcalendar, calendar.to_ical(), outfile)


if __name__ == '__main__':
    fire.Fire()