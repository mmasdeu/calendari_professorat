"""HTTP-only variant of the calendar generator.

This version replaces Playwright/browser automation with direct calls to the
public UAB JSON and ICS endpoints while keeping the higher-level calendar and
HTML generation behavior aligned with the original script.
"""

from icalendar import Calendar, Event, vDatetime, vDate
from uuid import uuid4
from urllib.parse import quote
import sys, os, re, base64, fire
import json
import requests
from time import sleep
from contextlib import nullcontext
from datetime import timedelta, datetime
import unicodedata

URL_GUIES_DOCENTS = "https://guies.uab.cat/guies_docents/public/portal/html/"
URL_PDS = "https://web01.uab.es:31501/pds/"
URL_TPD = URL_PDS + "transparenciaPD/"
URL_HORARIS = URL_PDS + "consultaPublica/look%5Bconpub%5DInicioPubHora?entradaPublica=true&idiomaPais=ca.ES"
HOME = os.getenv('HOME')
USER = 'masdeu'

# Set the academic year for constructing URLs to subject pages (for linking in the HTML output)
# Get it from datetime.now() and assume that if we're in the first half of the year, the academic year is the previous year / current year, otherwise it's current year / next year
CURS = datetime.now().year - 1 if datetime.now().month < 8 else datetime.now().year

BASE_URL = f"https://mat.uab.cat"
if 'home' not in HOME:
    HOME = f'/home/{USER}'  # default fallback for use with things like /var/www

# BASE_FOLDER = https://mat.uab.cat/~masdeu/teaching/misc/
CACHED_CALENDARS_DIR = HOME + '/cached_calendars'  # Directory to cache downloaded calendars
LOG_FILE = CACHED_CALENDARS_DIR + '/logfile.txt'  # Log file path
EXCLUDED_GROUPS = ['PEXT','TFG', 'TFM']

centres_dict = dict([
    ("Biociències", 113),
    ("Ciències", 103),
    ("Ciències de l'Educació", 111),
    ("Ciències de la Comunicació", 105),
    ("Ciències Polítiques i Sociologia", 108),
    ("Dret", 106),
    ("Economia i Empresa", 114),
    ("Filosofia i Lletres", 101),
    ("Medicina", 102),
    ("Veterinària", 107),
    ("Enginyeria", 115),
    ("Escola de Doctorat", 600),
    ("Formació Permanent", 650)
])

codi_departaments  = dict([   
(402,"Matemàtiques"),
(403,"Química"),
(404,"Física"),
(405,"Geologia"),
(406,"Bioquímica i Biologia Molecular"),
(407,"Biologia Animal, Biologia Vegetal i Ecologia"),
(409,"Genètica i Microbiologia"),
])


departaments_dict = {nom : cod for cod, nom in codi_departaments.items()}
codi_centres = {cod : nom for nom, cod in centres_dict.items()}

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def write_log(message):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f'[{timestamp}] {message}\n'
    with open(LOG_FILE, 'a') as log_file:
        log_file.write(log_message)


def academic_year_start(now=None):
    now = now or datetime.now()
    return now.year - 1 if now.month < 8 else now.year


def java_hashcode(value):
    # The public horaris endpoint keys selected subjects by Java's String.hashCode().
    # Match Java's String.hashCode() and keep 32-bit signed overflow semantics.
    h = 0
    for ch in value:
        h = (31 * h + ord(ch)) & 0xFFFFFFFF
    if h & 0x80000000:
        h -= 0x100000000
    return h


def normalize_period(period_value):
    value = str(period_value or '').strip()
    if not value or value == '-1':
        return '-1'
    if '/' in value:
        return value
    return f'{value}/0'


def expand_assignatures_for_request(llista_assignatures):
    expanded = []
    for a in llista_assignatures:
        if any(o in a.grup for o in EXCLUDED_GROUPS):
            continue
        if str(a.periode) == '-1':
            expanded.append(Assignatura(a.centre, a.codi, a.grup, 'A/0', a.nom))
            expanded.append(Assignatura(a.centre, a.codi, a.grup, 'C/1', a.nom))
            expanded.append(Assignatura(a.centre, a.codi, a.grup, 'C/2', a.nom))
        else:
            expanded.append(Assignatura(a.centre, a.codi, a.grup, normalize_period(a.periode), a.nom))
    return expanded


class UABPDSClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) calendari_professorat/1.0',
            'Accept-Language': 'ca,es;q=0.9,en;q=0.8',
        })
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    def _post_json(self, url, data=None):
        response = self.session.post(url, data=data, timeout=45)
        if not response.encoding:
            response.encoding = 'iso-8859-1'
        try:
            return response.json()
        except Exception as exc:
            raise RuntimeError(f'JSON invàlid a {url}: {exc}') from exc

    def professors_departament(self, codi_departament):
        self.session.get(URL_TPD + "InicioTransparencia?entradaPublica=true&idioma=ca&pais=ES#", timeout=45)
        payload = {'departamento': str(codi_departament)}
        data = self._post_json(URL_TPD + 'obtenerProfesoresDepartamento', payload)
        if data.get('code') != 200:
            return []
        return data.get('data', {}).get('result', {}).get('list', [])

    def fitxa_professor(self, codi_departament, area_coneixement, dnii_id):
        payload = {
            'departamento': str(codi_departament),
            'areaConocimiento': str(area_coneixement),
            'dniiId': str(dnii_id),
        }
        data = self._post_json(URL_TPD + 'obtenerFichaProfesor', payload)
        if data.get('code') != 200:
            return None
        return data.get('data', {}).get('result', {})

    def _build_subject_filter(self, assignatures):
        year = str(academic_year_start())
        filters = {}
        for a in assignatures:
            period = normalize_period(a.periode)
            element = {
                'anoAcademico': year,
                'asignatura': str(a.codi),
                'asignaturaDesc': str(a.nom or a.codi),
                'centro': str(a.centre),
                'centroDesc': str(a.centre),
                'plan': '-1',
                'planDesc': '',
                'estudio': '',
                'estudioDesc': '',
                'periodo': period,
                'periodoDesc': period,
                'grupo': '-1',
                'grupoDesc': '-1',
                'indExamen': 'true',
            }
            # The server ignores arbitrary object keys here; they must match jPubhora.crearHash().
            hash_source = f"{element['asignatura']}//{element['centro']}//{element['plan']}//{element['estudio']}//{element['indExamen']}//{element['periodo']}//{element['grupo']}"
            filters[str(java_hashcode(hash_source))] = element
        return filters

    def calendari_from_assignatures(self, llista_assignatures):
        assignatures = expand_assignatures_for_request(llista_assignatures)
        if not assignatures:
            return None
        self.session.get(URL_HORARIS, timeout=45)
        json_filters = self._build_subject_filter(assignatures)
        form_data = {
            'jsonBusquedaAsignaturas': json.dumps(json_filters, ensure_ascii=False),
            'limpiarParametrosBusqueda': 'N',
            'idPestana': '0',
            'ultimoPlanDocente': str(academic_year_start()),
            'accesoSecretaria': 'null',
        }
        # Reproduce the same two-step flow the browser uses before asking for the ICS blob.
        self.session.post(URL_PDS + 'consultaPublica/look%5Bconpub%5DActualizarPestanaPubHora?rnd=1', data=form_data, timeout=45)
        self.session.post(URL_PDS + 'consultaPublica/look%5Bconpub%5DMostrarPubHora?rnd=1', data=form_data, timeout=45)
        ics_response = self._post_json(URL_PDS + 'control/%5BmtoGenerarICS%5D', data={})
        if ics_response.get('code') != 200:
            return None
        ics_b64 = ics_response.get('data', {}).get('result')
        if not ics_b64:
            return None
        ics_bytes = base64.b64decode(ics_b64)
        return Calendar.from_ical(ics_bytes)


def extreu_assignatures_de_fitxa(fitxa):
    resultat = []
    vistos = set()
    for bloc in fitxa.get('gruposDocencia', []):
        centre = str(bloc.get('codCentro', '-1'))
        for assignatura in bloc.get('list', []):
            print(assignatura)
            codi = str(assignatura.get('codAsig', ''))
            nom = str(assignatura.get('desc', ''))
            for grup in assignatura.get('grupos', []):
                desc_grup = str(grup.get('descGrupo') or '-1').strip()
                
                hores = float(grup.get('grupHoraAlum') or -1)
                # print(hores)
                tipus_periode = str(grup.get('tipoPeriodo') or '-1').strip()
                valor_periode = str(grup.get('valorPeriodo') or '-1').strip()
                periode = f'{tipus_periode}/{valor_periode}' if tipus_periode != '-1' and valor_periode != '-1' else '-1'
                key = (centre, codi, desc_grup, periode)
                if hores > 0 and codi and key not in vistos:
                    vistos.add(key)
                    resultat.append(Assignatura(centre, codi, desc_grup, periode, nom))
    return resultat

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
        # start with a palette of 20 distinct colors (enough for all subjects without needing to repeat)
        base_colors = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
            '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
            '#393b79', '#637939', '#8c6d31', '#843c39', '#7b4173',
            '#3182bd', '#e6550d', '#31a354', '#de2d26', '#756bb1'
        ]
        index = int(self.codi) % len(base_colors)
        # use the grup attribute to modify the color slightly (changing the brightness):
        if self.grup != '-1':
            # parse group number if possible
            try:
                grup_num = int(re.search(r'\d+', self.grup).group())
            except:
                grup_num = 0
            # modify the base color by adjusting its brightness based on the group number
            def adjust_brightness(hex_color, factor):
                hex_color = hex_color.lstrip('#')
                r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
                r = min(255, max(0, int(r * factor)))
                g = min(255, max(0, int(g * factor)))
                b = min(255, max(0, int(b * factor)))
                return f'#{r:02x}{g:02x}{b:02x}'
            brightness_factor = 1 + (grup_num % 3) * 0.1  # vary brightness by up to ±20%
            return adjust_brightness(base_colors[index], brightness_factor)
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
        'Examen': 'EX',
        'Pràctiques Externes': 'PEXT',
        'Treball de Final de Grau': 'TFG'
    }
    tipus = tipus_abbrev.get(tipus_full, tipus_full)
    return tipus if grup is None else f'{tipus}/{grup}'

def normalize_block_list(block_list):
    if block_list is None:
        return []
    if isinstance(block_list, (int, str)):
        block_list = [block_list]
    normalized = []
    for item in block_list:
        for part in str(item).split(','):
            code = part.strip()
            if code and code not in normalized:
                normalized.append(code)
    return normalized

def imprimeix_html(events, ics_string, outfile=None, standalone=None):
    ics_string = ics_string.decode('utf-8').replace('\r\n', '\n').strip()
    if standalone is None:
        standalone = not bool(outfile)
    with open(outfile + '.html', 'w') if outfile else nullcontext(sys.stdout) as f:
        if standalone:
            f.write(f'<html><head>\
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/index.global.min.css">\
            <link rel="stylesheet" href="{BASE_URL}/~masdeu/teaching/misc/calendari_style.css">\
            <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/index.global.min.js"></script>\
            <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/locales-all.min.js"></script>\
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

                   initialView: "timeGridWeek",
                    headerToolbar: {
                        left: 'prev,next,today',
                        center: 'title',
                        right: 'timeGridWeek,listMonth'
                    },
                                        buttonText: {
                                                today: 'avui',
                                                week: 'setmana',
                                                list: 'llista'
                                        },
                      titleFormat: { // will produce something like "Tuesday, September 18, 2018"
                        month: 'numeric',
                        year: 'numeric',
                        day: 'numeric'
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

def find_professor(name, codi):
    codi = int(codi)
    client = UABPDSClient()
    professors = client.professors_departament(codi)
    tokens = [n.strip().lower() for n in str(name).split(' ') if n.strip()]
    for idx, prof in enumerate(professors):
        professor = str(prof.get('nombreCompleto', ''))
        if all(token in professor.lower() for token in tokens):
            eprint(f'Professor/a "{professor}" trobat al número {idx}.')
            return professor
    return None

def build_database(name, codi):
    codi = int(codi)
    professor_names = []
    if name is None or name == 'None':
        # Find oldest file in cached_calendars/
        try:
            os_files = [f for f in os.listdir(CACHED_CALENDARS_DIR) if f.startswith(f'prof_{codi}_') and f.endswith('.data')]
        except FileNotFoundError:
            os_files = []
        # Calculate the oldest modification time
        try:
            oldest_file = min(os_files, key=lambda f: os.path.getmtime(os.path.join(CACHED_CALENDARS_DIR, f)))
            eprint(f'{oldest_file = }')
            with open(os.path.join(CACHED_CALENDARS_DIR, oldest_file), 'r') as of:
                fullname = of.readline().strip('\n')
            professor_names = [fullname]
        except ValueError:
            professor_names = []
    elif name == 'all':
        client = UABPDSClient()
        professors = client.professors_departament(codi)
        professor_names = [str(p.get('nombreCompleto', '')) for p in professors if p.get('nombreCompleto')]
        nprofs = len(professor_names)
        eprint('Total professors found:', nprofs)
    else:
        professor_names = [str(name)]
    ans = []        
    for fullname in professor_names:
        while True:
            try:
                professor, assignatures = get_assignatures(fullname, codi, exact=False)
                break
            except Exception as e:
                eprint(f'Error obtenint assignatures del professor/a {fullname}: ', str(e))
                sleep(1)
        # Elimina assignatures que no es volen processar (per exemple, tesis doctorals *68000) o
        # les pràctiques externes (acabades en 69)
        assignatures = [a for a in assignatures if not any(g in a.grup for g in EXCLUDED_GROUPS) and a.codi not in ['68000'] and a.codi[:2] != '69']
        eprint('Processant professor', professor, 'amb', len(assignatures), 'assignatures...', end=' ')
        sys.stderr.flush()
        if len(assignatures) > 0:
            prof_str = professor.replace(' ', '_').replace('/', '_').replace(',', '_').replace('ñ', 'n').replace('Ñ', 'N')
            fname = f'{CACHED_CALENDARS_DIR}/prof_{codi}_{prof_str}.data'
            cal = descarrega_calendari(assignatures)
            if cal is None:
                eprint('Error descarregant el calendari per al professor/a', professor)
                cal = Calendar()
                continue
            with open(fname, "wb") as f:
                f.write(professor.encode('utf-8') + b'\n')
                f.write(str(len(assignatures)).encode('utf-8') + b'\n')
                for a in assignatures:
                    f.write(a.to_string().encode('utf-8') + b'\n')
                f.write(cal.to_ical())
            os.chmod(fname, 0o666)
        else:
            cal = Calendar()
        eprint('Fet!')    
        ans.append((professor, assignatures, cal))
    return ans


def get_assignatures_nthprofessor(n, codi):
    codi = int(codi)
    client = UABPDSClient()
    professors = client.professors_departament(codi)
    if n < 0 or n >= len(professors):
        return None, []
    selected = professors[n]
    professor = str(selected.get('nombreCompleto', ''))
    fitxa = client.fitxa_professor(codi, selected.get('areaConocimiento'), selected.get('DniiId'))
    if fitxa is None:
        return professor, []
    return professor, extreu_assignatures_de_fitxa(fitxa)


def get_assignatures(name, codi, exact=False):
    codi = int(codi)
    client = UABPDSClient()
    professors = client.professors_departament(codi)
    if exact:
        selected = next((p for p in professors if str(p.get('nombreCompleto', '')).strip().lower() == str(name).strip().lower()), None)
    else:
        tokens = [n.strip().lower() for n in str(name).split(' ') if n.strip()]
        selected = next((p for p in professors if all(t in str(p.get('nombreCompleto', '')).lower() for t in tokens)), None)
    if selected is None:
        eprint(f"No s'ha trobat cap professor/a amb el nom '{name}'.")
        return None, []
    professor = str(selected.get('nombreCompleto', ''))
    fitxa = client.fitxa_professor(codi, selected.get('areaConocimiento'), selected.get('DniiId'))
    if fitxa is None:
        return professor, []
    return professor, extreu_assignatures_de_fitxa(fitxa)

def descarrega_calendari(llista_assignatures):
    if not isinstance(llista_assignatures, list):
        llista_assignatures = [llista_assignatures]
    client = UABPDSClient()
    try:
        return client.calendari_from_assignatures(llista_assignatures)
    except Exception as e:
        eprint(f'Error al carregar el calendari: {e}')
        return None

def genera_calendari(llista_assignatures, include_holidays=True, calendari=None, block_list=None):
    # Process events and keep only those corresponding to our subjects
    block_list = normalize_block_list(block_list)
    newcal = Calendar()
    events_fullcalendar = []
    if calendari is None:
        calendari = descarrega_calendari(llista_assignatures)
    if calendari is None:
        eprint('Error: No s\'ha pogut descarregar el calendari.')
        return newcal, events_fullcalendar
    seen_events = set()
    seen_holidays = set()
    for event in calendari.events:
        data = str(event.get('SUMMARY'))
        lloc = str(event.get('LOCATION')).replace('Aula de docència', '').replace('d`', '').strip(' - ').strip()
        if lloc == 'None':
            lloc = '** aula no assignada **'
        start = event.get('DTSTART')
        end = event.get('DTEND')
        # Extract code, name, group, type using regex: 100088 - Àlgebra Lineal Grup: 2 - Pràctiques d'Aula
        match = re.match(r'(\d+)\s*-\s*(.*?)\s*Grup:\s*(\d+)\s*-\s*(.*)', data)
        if match:
            # Skip if event is duplicate (same summary, location, start, end)
            event_id = (data, lloc, start, end)
            if event_id in seen_events:
                continue
            seen_events.add(event_id)

            codi, nom_assignatura, grup, tipus = match.groups()
            title = f'{codi} {nom_assignatura} ({t_abbrev(tipus)}/{grup}) ➤ {lloc}'
            if str(codi) not in block_list:
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
            is_allday = 'dia' in data.lower() \
                    or 'festiu' in data.lower() \
                    or (end.dt - start.dt) > timedelta(hours=9)
            if is_allday:
                # Set event to be all-day
                event.add('dtstart', vDate(start.dt))
                # End one day later
                event.add('dtend', vDate(end.dt+timedelta(days=1)))
            else:
                event.add('dtstart', vDatetime(start.dt))
                event.add('dtend', vDatetime(end.dt))
            event.add('DTSTAMP', vDatetime(start.dt))
            event.add('UID', str(uuid4()) + '@mat.uab.cat')
            # Skip if event is duplicate (same summary, location, start, end)
            # if 'festiu' in data, look only at date, not time
            if is_allday:
                date = start.dt.date()
                event_id = (data, date)
            else:
                event_id = (data, str(start.dt), str(end.dt))
            if event_id in seen_holidays:
                continue
            else:
                seen_holidays.add(event_id)
                newcal.add_component(event) # Add non-lecture days to the ICS
                events_fullcalendar.append((data, str(start.dt), str(end.dt), '#808080', is_allday))
    return newcal, events_fullcalendar

def imprimeix_llista_assignatures(llista_assignatures, html=True, outfile=None, blocked_codes=None):
    blocked_codes = set(normalize_block_list(blocked_codes))
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
        # f.write(f'Centre/Codi{tab}Nom de l\'assignatura{tab}(Període), grups' + end)
        if html:
            f.write('<h3>Assignatures</h3>')
        else:
            f.write(sep)
        for (centre, codi, periode), assignatures in dict_assignatures.items():
            if html:
                url_assignatura = URL_GUIES_DOCENTS + f"{CURS}/assignatura/{codi}/ca"
                text_codi = f'<a href="{url_assignatura}"><b>{centre}</b> ({codi_centres.get(int(centre), "?")}) / <b>{codi}</b></a>'
                blocked_class = ' is-blocked' if str(codi) in blocked_codes else ''
                course_name = assignatures[0].nom_curt().strip()
                text_nom = f'<button type="button" class="block-course-label{blocked_class}" data-course-code="{codi}" aria-pressed="{"true" if str(codi) in blocked_codes else "false"}" title="Clica per bloquejar/desbloquejar">{course_name}</button>'
            else:
                text_codi = f'{centre} ({codi_centres.get(int(centre), "?")}) / {codi}'
                text_nom = assignatures[0].nom_curt()
            per = 'C1' if periode == 'C/1' else 'C2' if periode == 'C/2' else 'A'
            linia = f'{text_codi}\t{text_nom} · {per} '
            grups = ', '.join(sorted(set(a.grup for a in assignatures)))
            linia += f'({grups})'
            f.write(linia.replace('\t', tab) + end)
        f.write(sep)

## Called from php when ?feed=true is in the URL parameters, to directly output the ICS feed
def fes_feed(name, codi=402, include_holidays=True, block_list=None):
    professor, llista_assignatures, calendari = llegeix_fitxer_calendari(name, codi)
    if professor is None:
        return
    calendar, _ = genera_calendari(llista_assignatures, include_holidays=include_holidays, calendari=calendari, block_list=block_list)
    # Generate ICS feed directly to stdout
    sys.stdout.buffer.write(calendar.to_ical())
    write_log(f'Feed generat per "{name}" ({codi}) amb {len(llista_assignatures)} assignatures.')
    return
## Called from php
def fes_web_assignatura(centre, codi=402, include_holidays=True, block_list=None):
    assignatura = Assignatura(centre, codi)
    calendar, events_fullcalendar = genera_calendari([assignatura], include_holidays=include_holidays, block_list=block_list)
    imprimeix_html(events_fullcalendar, calendar.to_ical(), outfile=None, standalone=False)
    write_log(f'Web generada per assignatura {centre} {codi}.')
    return

def remove_accents(input_string):
    # Normalize the string to decompose accented characters into their base characters and diacritics
    nfkd_form = unicodedata.normalize('NFKD', input_string)
    # Filter out the diacritics (characters with Unicode category 'Mn')
    return ''.join([c for c in nfkd_form if not unicodedata.combining(c)])

def llegeix_fitxer_calendari(name, codi):
    codi = int(codi)
    # Use cached_calendars directory
    name_words = [remove_accents(n.strip().lower()) for n in name.split(' ')]
    try:
        os_files = [f for f in os.listdir(CACHED_CALENDARS_DIR) if f.startswith(f'prof_{codi}_') and f.endswith('.data')]
    except FileNotFoundError:
        os_files = []
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
        fullname = find_professor(name, codi)
        if fullname is None:
            return None, [None], None
        else:
            ans = build_database(fullname, codi)
            if len(ans) > 0:
                return ans[0]
            else:
                print("No s'ha trobat cap professor/a amb el nom especificat.\n")
                return None, [None], None
    return professor, llista_assignatures, calendari

def fes_web_calendari(name, codi=402, include_holidays=True, block_list=None):
    if '/' in name:
        centre, codi = name.split('/', 1)
        return fes_web_assignatura(centre, codi, include_holidays=include_holidays)

    llista_assignatures = []
    calendari = Calendar()
    professor_list = []
    for n in name.split(';'):
        professor, assignatures, calendari_nou = llegeix_fitxer_calendari(n.strip(), codi)
        professor_list.append(professor)
        for a in assignatures:
            if a not in llista_assignatures:
                llista_assignatures.append(a)
        # llista_assignatures.extend(assignatures)
        if calendari_nou is not None:
            # Merge events from calendari_nou into calendari
            for event in calendari_nou.events:
                calendari.add_component(event)
    if all(o is None for o in professor_list):
        return

    blocked_codes = normalize_block_list(block_list)
    blocked_codes_js = '[' + ','.join(f'"{code}"' for code in blocked_codes) + ']'

    print(f'Professorat trobat: {str(professor_list)[1:-1]}', end='<br><br>\n')


    imprimeix_llista_assignatures(llista_assignatures, html=True, outfile=None, blocked_codes=blocked_codes)

    print('''
    <input type="checkbox" id="includeHolidays" ''' + ('checked' if include_holidays else '') + '''>
    Incloure festius i no lectius</label><br>'''
    )

    calendar, events_fullcalendar = genera_calendari(llista_assignatures,
                                                     include_holidays=include_holidays,
                                                     calendari=calendari,
                                                     block_list=blocked_codes)
  
    imprimeix_html(events_fullcalendar, calendar.to_ical(), outfile=None, standalone=False)

    # Write feed generating url in a box, with a copy to clipboard button
    name_safe = quote(name)
    feed_url = f'{BASE_URL}/calendari_professorat?nom={name_safe}&departament={codi}&holidays={str(include_holidays).lower()}&feed=true'
    if blocked_codes:
        feed_url += '&block=' + ','.join(blocked_codes)

    # Render feed URL box with a checkbox to toggle inclusion of holidays
    print('''
    <style>
    .block-course-label {
        border: 0;
        padding: 0;
        background: transparent;
        color: inherit;
        font: inherit;
        cursor: pointer;
        text-align: left;
    }
    .block-course-label:hover {
        text-decoration: underline;
    }
    .block-course-label.is-blocked {
        color: #666;
        text-decoration: line-through;
    }
    </style>
    <div style="margin-bottom: 10px;">
    URL del feed iCal:<br>
    <input type="text" id="feedUrl" value="''' + feed_url + '" readonly data-name="''' + name_safe + '''" data-departament="''' + str(codi) + '''">
    <button id="copyFeedUrl">Copia</button><label style="margin-left:10px; font-weight:normal;">
    </div>
    ''')

    print('''
    <script>
    (function(){
        var feedInput = document.getElementById("feedUrl");
        var checkbox = document.getElementById("includeHolidays");
        var copyBtn = document.getElementById("copyFeedUrl");
        var blockedCodes = ''' + blocked_codes_js + ''';
        var courseLabels = Array.prototype.slice.call(document.querySelectorAll('.block-course-label'));

        function buildUrl(includeFeed) {
            var url = new URL(window.location.origin + window.location.pathname);
            var currentBlocked = courseLabels.filter(function(label) { return label.classList.contains('is-blocked'); }).map(function(label) { return label.getAttribute('data-course-code'); });
            url.searchParams.set('nom', decodeURIComponent(feedInput.getAttribute('data-name')));
            url.searchParams.set('departament', feedInput.getAttribute('data-departament'));
            url.searchParams.set('holidays', checkbox.checked ? 'true' : 'false');
            if (includeFeed) {
                url.searchParams.set('feed', 'true');
            }
            if (currentBlocked.length > 0) {
                url.searchParams.set('block', currentBlocked.join(','));
            } else {
                url.searchParams.delete('block');
            }
            return url;
        }

        function updateFeedUrl() {
            feedInput.value = buildUrl(true).toString();
        }

        courseLabels.forEach(function(label) {
            if (blockedCodes.indexOf(label.getAttribute('data-course-code')) >= 0) {
                label.classList.add('is-blocked');
                label.setAttribute('aria-pressed', 'true');
            }
            label.addEventListener('click', function() {
                var isBlocked = label.classList.toggle('is-blocked');
                label.setAttribute('aria-pressed', isBlocked ? 'true' : 'false');
                updateFeedUrl();
                window.location.assign(buildUrl(false).toString());
            });
        });
        checkbox.addEventListener('change',function() {
                updateFeedUrl();
                window.location.assign(buildUrl(false).toString());
            });
        updateFeedUrl();

        copyBtn.addEventListener("click", function() {
            feedInput.select();
            feedInput.setSelectionRange(0, 99999); // For mobile
            document.execCommand("copy");
            alert("Copiat l'URL del feed: " + feedInput.value);
        });
    })();
    </script>
    ''')
    write_log(f'Web generada per a "{name}" ({codi}) block={block_list} amb {len(llista_assignatures)} assignatures.')
    return

def main(name, codi=402, out_ics=True, out_html=True, outfile='calendari', include_holidays=True, block_list=None):
    professor, llista_assignatures, calendari = llegeix_fitxer_calendari(name, codi)
    if professor is None:
        return
    calendar, events_fullcalendar = genera_calendari(llista_assignatures, include_holidays=include_holidays, calendari=calendari, block_list=block_list)
    print(f'Professorat trobat: {professor}')
    imprimeix_llista_assignatures(llista_assignatures, html=False, outfile=None)
    if out_ics:
        # Save new calendar to file
        with open(outfile + '.ics', "wb") if outfile else nullcontext(sys.stdout) as f:
            f.write(calendar.to_ical())
    if out_html:
        imprimeix_html(events_fullcalendar, calendar.to_ical(), outfile)

if __name__ == '__main__':
    fire.Fire()
