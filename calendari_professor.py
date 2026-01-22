from hmac import new
from tkinter import W
from playwright.sync_api import sync_playwright, expect, Error
from playwright._impl._errors import TimeoutError
from icalendar import Calendar, Event, vDatetime, vDate
from uuid import uuid4
from urllib.parse import quote
import sys, os, re, base64, fire
from webbrowser import open as webbrowser_open
from time import sleep
from contextlib import nullcontext
from datetime import date, timedelta

URL_TPD = "https://web01.uab.es:31501/pds/transparenciaPD/InicioTransparencia?entradaPublica=true&idioma=ca&pais=ES#"
URL_HORARIS = "https://web01.uab.es:31501/pds/consultaPublica/look%5Bconpub%5DInicioPubHora?entradaPublica=true&idiomaPais=ca.ES"  # <-- set the page URL where the original script runs
HOME = os.getenv('HOME')
if 'home' not in HOME:
    HOME = '/home/masdeu'  # default fallback for use with things like /var/www
BROWSER_PATH = HOME + "/.cache/ms-playwright/chromium_headless_shell-1200/chrome-headless-shell-linux64/chrome-headless-shell"  # <-- set the path to your Chromium browser executable
CACHED_CALENDARS_DIR = HOME + '/cached_calendars'  # Directory to cache downloaded calendars

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def carrega_assignatures(page, llista_assignatures):
    # Prepare the list of subjects
    llista_assignatures_new = []
    for a in llista_assignatures:
        if str(a.periode) == '-1':
            llista_assignatures_new.append(Assignatura(a.centre, a.codi, a.grup, 'A/0', a.nom))
            llista_assignatures_new.append(Assignatura(a.centre, a.codi, a.grup, 'C/1', a.nom))
            llista_assignatures_new.append(Assignatura(a.centre, a.codi, a.grup, 'C/2', a.nom))
        else:
            llista_assignatures_new.append(a)
    txt = ','.join((f'crea_element("{a.codi}", "{a.centre}", "{a.periode}")' for a in llista_assignatures_new))
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
    # Expect blobData to be of length > 0
    while page.evaluate("document.blobData") is None:
        page.wait_for_timeout(10)
    return Calendar.from_ical(page.evaluate("document.blobData"))


text_genera_assignatures = '''
        (function(){
        function collectCodes(){
            var tables = document.querySelectorAll('table.tablaFicha.taulaFitxa.centros');
            var result = {};
            var codeRe = /\\d{4,6}/; // capture code digits
            var fullCodeCellRe = /^\\s*(\\d{4,6})(?:\\s*[-–:]\\s*(.*))?$/; // "101742 - Course Name"
            var slashPattern = '([A-Za-zÀ-ÿ0-9.\\-]{1,20})\\s*\\/\\s*(\\d{1,3})';
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
                else { var m = raw.match(codeRe); if(m){ rawCode = m[0]; codeCellIdx = codiIdx; var rest = raw.replace(m[0],'').replace(/^\\s*[-–:]?\\s*/,'').trim(); if(rest) rawName = rest; } }
                }

                if(!rawCode){
                for(var i=0;i<tds.length;i++){
                    var txt = (tds[i].textContent||'').trim();
                    var mFull2 = txt.match(fullCodeCellRe);
                    if(mFull2){ rawCode = mFull2[1]; rawName = (mFull2[2]||'').trim(); codeCellIdx = i; break; }
                    var md = txt.match(codeRe);
                    if(md){ rawCode = md[0]; codeCellIdx = i; var after = txt.replace(md[0],'').replace(/^\\s*[-–:]?\\s*/,'').trim(); if(after) rawName = after; else if(i+1<tds.length) rawName = (tds[i+1].textContent||'').trim(); break; }
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
                var codicentre = centre.match(/\\d+/)[0];
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
                lines.push('(' + codicentre + ', ' + code + ', ' + grp + (period ? ', '+period : '') + (name ? ', '+name : '') + ')');
            });
            });
            document.llista_assignatures = '[' + lines.join(',') + ']';
            document.llista_assignatures_done = true;
        // For debugging: also expose a function to get the data object
        window.collectSiaCodesData = collectCodes;
        })();   
    '''

class Assignatura():
    def __init__(self, centre, codi=None, grup=-1, periode=-1, nom=''):
        if codi is None:
            # parse from string
            s = str(centre)
            parts = s.split('++')
            self.centre = parts[0]
            self.codi = parts[1] if len(parts) > 1 else ''
            self.nom = parts[2] if len(parts) > 2 else ''
            self.periode = parts[3] if len(parts) > 3 else '-1'
            self.grup = parts[4] if len(parts) > 4 else '-1'
            return
        self.centre = str(centre)
        self.codi = str(codi)        
        self.grup = str(grup)
        self.periode = str(periode)
        self.nom = str(nom)

    def to_string(self):
        return f'{self.centre}++{self.codi}++{self.nom}++{self.periode}++{self.grup}'
    

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
        return iter((self.centre, self.codi, self.grup, self.periode, self.nom))
    
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
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/main.min.css">\
            <link rel="stylesheet" href="calendari_style.css">\
            <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/main.min.js"></script>\
            <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/locales-all.min.js"></script>\
            <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/index.global.min.js"></script>\
            <script src="https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"></script>\
            </head><body>\n')
        f.write('<button id="icaldownload" style="float: right; margin-bottom: 10px;">Descarrega</button>\n')
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
                    headerToolbar: {
                        left: 'prev,next,today',
                        center: 'title',
                        right: 'listMonth,timeGridWeek'
                    },
                    contentHeight:"auto",
                    views: {
                        timeGridWeek: {
                            slotMinTime: "08:00:00",
                            slotMaxTime: "20:00:00"
                        }
                    },
                    weekends: false,                 
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
        # webbrowser_open('file://' + base_folder + '/' + outfile + '.html')

def find_professor_number(name):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=BROWSER_PATH)
        # navigate to page
        page = browser.new_page()
        while True:
            try:
                page.goto(URL_TPD)
                break
            except Error:
                sleep(.2)
                page.goto(URL_TPD)        
        page.get_by_role('link', name='Pla Docent per departament').click(force=True)
        page.get_by_role('gridcell', name='Departament de matemàtiques').click(force=True)
        page.wait_for_load_state('networkidle')
        nprofs = page.locator('[class="profesorDepartamento"]').count()
        for i in range(nprofs):
            link = page.locator('[class="profesorDepartamento"]').nth(i)
            professor = link.inner_text()
            if all(n.strip().lower() in professor.strip().lower() for n in name.split(' ')):
                eprint(f'Professor/a "{professor}" trobat al número {i}.')
                browser.close()
                return i
        browser.close()
    return None

def build_database(start = 0, end=None):
    if start == -1:
        # Find oldest file in cached_calendars/
        os_files = [f for f in os.listdir(CACHED_CALENDARS_DIR) if f.startswith('prof_') and f.endswith('.data')]
        # Calculate the oldest modification time
        try:
            oldest_file = min(os_files, key=lambda f: os.path.getmtime(os.path.join(CACHED_CALENDARS_DIR, f)))
            start = int(oldest_file.split('_')[1])
            end = start + 1
        except ValueError:
            start = 0
            end = None
    if end is None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=BROWSER_PATH)
            # navigate to page
            page = browser.new_page()
            while True:
                try:
                    page.goto(URL_TPD)
                    break
                except Error:
                    sleep(.2)
                    page.goto(URL_TPD)        
            page.get_by_role('link', name='Pla Docent per departament').click(force=True)
            page.get_by_role('gridcell', name='Departament de matemàtiques').click(force=True)
            page.wait_for_load_state('networkidle')
            nprofs = page.locator('[class="profesorDepartamento"]').count()
            browser.close()
        eprint('Total professors found:', nprofs)
        end = nprofs
    for i in range(start, end):
        ans = []
        while True:
            try:
                professor, assignatures = get_assignatures_nthprofessor(i)
                break
            except Exception as e:
                eprint('Error obtenint assignatures del professor/a número', i, ':', str(e))
                sleep(1)
        eprint('Processant professor número:', i, 'Nom:', professor, 'amb', len(assignatures), 'assignatures...', end=' ')
        sys.stderr.flush()
        if len(assignatures) > 0:
            prof_str = professor.replace(' ', '_').replace('/', '_').replace(',', '_')
            fname = f'{CACHED_CALENDARS_DIR}/prof_{i:03}_{prof_str}.data'
            cal = descarrega_calendari(assignatures)
            if cal is None:
                eprint('Error descarregant el calendari per al professor/a', professor)
                continue
            with open(fname, "wb") as f:
                f.write(professor.encode('utf-8') + b'\n')
                f.write(str(len(assignatures)).encode('utf-8') + b'\n')
                for a in assignatures:
                    f.write(a.to_string().encode('utf-8') + b'\n')
                f.write(cal.to_ical())
            os.chmod(fname, 0o666)
        eprint('Fet!')
        ans.append((professor, assignatures, cal))
    return ans

def get_assignatures_nthprofessor(n):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=BROWSER_PATH)
        # navigate to page
        page = browser.new_page()
        while True:
            try:
                page.goto(URL_TPD)
                break
            except Error:
                sleep(.2)
                page.goto(URL_TPD)
        page.get_by_role('link', name='Pla Docent per departament').click(force=True)
        page.get_by_role('gridcell', name='Departament de matemàtiques').click(force=True)
        page.wait_for_load_state('networkidle')
        link = page.locator('[class="profesorDepartamento"]').nth(n)
        professor = link.inner_text()
        link.click(force=True)
        while page.get_by_text("Grups de docència impartits per centre").count() == 0:
            page.wait_for_timeout(100)
        page.wait_for_timeout(1000)
        page.evaluate(text_genera_assignatures)     
        while page.evaluate("document.llista_assignatures_done") is None:
            page.wait_for_timeout(100)
        llista_assignatures = [Assignatura(*o) for o in eval(page.evaluate('document.llista_assignatures'))]
        browser.close()
    return professor, llista_assignatures


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
                sleep(.2)
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
            browser.close()
            return None, []
        page.evaluate(text_genera_assignatures)     
        while page.evaluate("document.llista_assignatures_done") is None:
            page.wait_for_timeout(100)
        llista_assignatures = [Assignatura(*o) for o in eval(page.evaluate('document.llista_assignatures'))]
        browser.close()
    return professor, llista_assignatures

def descarrega_calendari(llista_assignatures):
    if not isinstance(llista_assignatures, list):
        llista_assignatures = [llista_assignatures]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=BROWSER_PATH)
        # navigate to page
        page = browser.new_page()
        while True:
            try:
                page.goto(URL_HORARIS)
                break
            except Error:
                sleep(.2)
                page.goto(URL_HORARIS)

        page.wait_for_load_state()
        page.get_by_text("Cerca per assignatura").click()
        # Wait until the form is completely loaded
        expect(page.get_by_text("Veure Calendari")).to_be_visible(timeout=20000)

        carrega_assignatures(page, llista_assignatures)
        try:
            expect(page.get_by_text("Tornar")).to_be_visible(timeout=20000)
            calendar = descarrega_calendari_sia(page)
        except (AssertionError,TimeoutError):
            eprint('Error al carregar el calendari...')
            calendar = None
        browser.close()
    return calendar

def genera_calendari(llista_assignatures, include_holidays=True, calendari=None):
    # Process events and keep only those corresponding to our subjects
    newcal = Calendar()
    events_fullcalendar = []
    if calendari is None:
        calendari = descarrega_calendari(llista_assignatures)
    if calendari is None:
        eprint('Error: No s\'ha pogut descarregar el calendari.')
        return newcal, events_fullcalendar
    for event in calendari.events:
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
                        ((a.grup == '-1') or (a.grup == t_abbrev(tipus,grup)) or (t_abbrev(tipus) == 'EX'))), None)
            if a is not None:
                event = Event()
                event['SUMMARY'] = data
                event['LOCATION'] = lloc
                event.add('dtstart', vDatetime(start.dt))
                event.add('dtend', vDatetime(end.dt))  # make end date exclusive
                event.add('DTSTAMP', event.get('DTSTAMP') if event.get('DTSTAMP') else vDatetime(start.dt))
                event.add('UID', str(uuid4()) + '@mat.uab.cat')
                newcal.add_component(event)
                events_fullcalendar.append((title, str(start.dt), str(end.dt), a.color(), False))
        elif include_holidays and start.dt.weekday() <= 4:  # Dies no lectius o similar
            data = data.replace(' - ','')
            event = Event()
            event['SUMMARY'] = data
            # If duration is longer than 9h, make it an all-day event
            if (end.dt - start.dt) > timedelta(hours=9):
                # Set event to be all-day
                event.add('dtstart', vDate(start.dt))
                # End one day later
                event.add('dtend', vDate(end.dt+timedelta(days=1)))
            else:
                event.add('dtstart', vDatetime(start.dt))
                event.add('dtend', vDatetime(end.dt))
            event.add('DTSTAMP', event.get('DTSTAMP') if event.get('DTSTAMP') else vDatetime(start.dt))
            event.add('UID', str(uuid4()) + '@mat.uab.cat')
            newcal.add_component(event) # Add non-lecture days to the ICS
            events_fullcalendar.append((data, str(start.dt), str(end.dt), '#808080', True))
    return newcal, events_fullcalendar

def imprimeix_llista_assignatures(llista_assignatures, html=True, outfile=None):
    if html:
        end = '<br>'
        sep = '<hr>'
        tab = '&nbsp;&nbsp;&nbsp;&nbsp;'
    else:
        end = ''
        sep = 30 * '-'
        tab = '\t'
    dict_assignatures = {(a.centre, a.codi, a.periode) : [] for a in llista_assignatures}
    for a in llista_assignatures:
        dict_assignatures[(a.centre, a.codi, a.periode)].append(a)
    with open(outfile + '.html', 'w') if outfile else nullcontext(sys.stdout) as f:
        f.write(f'Centre/Codi{tab}Nom de l\'assignatura{tab}(Període), grups' + end)
        f.write(sep)
        for (centre, codi, periode), assignatures in dict_assignatures.items():
            linia = f'{centre}/{codi}\t{assignatures[0].nom_curt()}\t({periode}), '
            grups = ', '.join(sorted(set(a.grup for a in assignatures)))
            linia += grups
            f.write(linia.replace('\t', tab) + end)
        f.write(sep)

def fes_feed(name, include_holidays=True):
    professor, llista_assignatures, calendari = llegeix_fitxer_calendari(name)
    if professor is None:
        return
    calendar, _ = genera_calendari(llista_assignatures, include_holidays=include_holidays, calendari=calendari)
    # Generate ICS feed directly to stdout
    sys.stdout.buffer.write(calendar.to_ical())
    return

def fes_web_assignatura(centre, codi, include_holidays=True):
    assignatura = Assignatura(centre, codi)
    calendar, events_fullcalendar = genera_calendari(assignatura, include_holidays=include_holidays)
    imprimeix_html(events_fullcalendar, calendar.to_ical(), outfile=None, standalone=False)
    return

def llegeix_fitxer_calendari(name):
    # Use cached_calendars directory
    name_words = [n.strip().lower() for n in name.split(' ')]
    os_files = [f for f in os.listdir(CACHED_CALENDARS_DIR) if f.startswith('prof_') and f.endswith('.data')]
    fname = next((f for f in os_files if all(n in f.lower() for n in name_words)), None)
    if fname is not None:
        with open(os.path.join(CACHED_CALENDARS_DIR, fname), 'rb') as f:
            professor = f.readline().decode('utf-8').strip()
            n_assignatures = int(f.readline().decode('utf-8').strip())
            llista_assignatures = []
            for _ in range(n_assignatures):
                a = Assignatura(f.readline().decode('utf-8').strip())
                llista_assignatures.append(a)
            calendari = Calendar.from_ical(f.read())
            eprint('Loaded data for professor:', professor)
    else:
        print('No s\'ha trobat cap professor/a amb el nom especificat.\n')
        n = find_professor_number(name)
        if n is None:
            return None, None, None
        else:
            return build_database(start=n, end=n+1)[0]
    return professor, llista_assignatures, calendari

def fes_web_calendari(name, include_holidays=True):
    if '/' in name:
        centre, codi = name.split('/', 1)
        return fes_web_assignatura(centre, codi, include_holidays=include_holidays)

    professor, llista_assignatures, calendari = llegeix_fitxer_calendari(name)
    if professor is None:
        return

    # Write feed generating url in a box, with a copy to clipboard button
    name_safe = quote(name)    
    feed_url = f'https://mat.uab.cat/~masdeu/teaching/misc/calendari_professor.php?nom={name_safe}&holidays={str(include_holidays).lower()}&feed=true'

    # Render feed URL box with a checkbox to toggle inclusion of holidays
    print('''
    <div style="margin-bottom: 10px;">
    URL del feed iCal:<br>
    <input type="text" id="feedUrl" value="''' + feed_url + '" readonly>'\
    + '''
    <button id="copyFeedUrl">Copia</button><label style="margin-left:10px; font-weight:normal;">
        <input type="checkbox" id="includeHolidays" ''' + ('checked' if include_holidays else '') + '''>
    Incloure dies no lectius</label>
    </div>
    <script>
    (function(){
        var feedInput = document.getElementById("feedUrl");
        var checkbox = document.getElementById("includeHolidays");
        var copyBtn = document.getElementById("copyFeedUrl");

        function updateFeedUrl() {
            var url = feedInput.value;
            // Replace existing holidays parameter if present, otherwise append it
            if (url.indexOf("&holidays=") >= 0) {
                url = url.replace(/(&holidays=)(true|false)/, '$1' + (checkbox.checked ? 'true' : 'false'));
            } else if (url.indexOf("?") >= 0) {
                url = url + '&holidays=' + (checkbox.checked ? 'true' : 'false');
            } else {
                url = url + '?holidays=' + (checkbox.checked ? 'true' : 'false');
            }
            feedInput.value = url;
        }

        checkbox.addEventListener('change', updateFeedUrl);

        copyBtn.addEventListener("click", function() {
            feedInput.select();
            feedInput.setSelectionRange(0, 99999); // For mobile
            document.execCommand("copy");
            alert("Copiat l'URL del feed: " + feedInput.value);
        });
    })();
    </script>
    ''')
    sys.stdout.flush()
    calendar, events_fullcalendar = genera_calendari(llista_assignatures, include_holidays=include_holidays, calendari=calendari)
    print(f'Professor/a trobat: {professor}', end='<br>\n')
    imprimeix_llista_assignatures(llista_assignatures, html=True, outfile=None)
    sys.stdout.flush()
    imprimeix_html(events_fullcalendar, calendar.to_ical(), outfile=None, standalone=False)
    return

def main(name, out_ics=True, out_html=True, outfile='calendari', include_holidays=True):
    professor, llista_assignatures, calendari = llegeix_fitxer_calendari(name)
    if professor is None:
        return
    calendar, events_fullcalendar = genera_calendari(llista_assignatures, include_holidays=include_holidays, calendari=calendari)
    print(f'Professor/a trobat: {professor}')
    imprimeix_llista_assignatures(llista_assignatures, html=False, outfile=None)
    if out_ics:
        save_ics(calendar, outfile)
    if out_html:
        imprimeix_html(events_fullcalendar, calendar.to_ical(), outfile)

if __name__ == '__main__':
    fire.Fire()