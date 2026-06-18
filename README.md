# Calendari del Professorat

Aquest repositori genera calendaris de docència en format iCal (ICS) i una vista web amb FullCalendar per professorat de la UAB.

El codi principal és a [calendari_professorat.py](calendari_professorat.py), i la
capa web està a [calendari_professor.php](calendari_professor.php), que invoca l'script Python per mostrar HTML i servir feeds ICS.

## Estructura del projecte

- [calendari_professorat.py](calendari_professorat.py): script principal.
- [calendari_professor.php](calendari_professor.php): frontend i passarel·la web cap al script Python.
- [calendari_style.css](calendari_style.css): estils de la sortida web.

## Requisits

Python 3.9 o superior recomanat.

Paquets:

- requests
- icalendar
- fire

## Instal·lació ràpida

1. Crear i activar un entorn virtual de Python.
2. Instal·lar dependències.

Exemple:

python -m pip install requests icalendar fire

## Ús per línia de comandes

Els scripts usen Fire, de manera que pots cridar funcions directament des de CLI.

Script: [calendari_professorat.py](calendari_professorat.py)

Generar fitxers locals ICS i HTML:

```
python calendari_professorat.py main --name="Nom Cognom" --codi=402 --outfile="calendari"
```

Generar HTML per web (stdout), per un o diversos professors separats per punt i coma:

```
python calendari_professorat.py fes_web_calendari --name="Nom Cognom;Altra Persona" --codi=402 --include_holidays=True
```

Generar feed ICS directe (stdout):

```
python calendari_professorat.py fes_web_calendari --name="Nom Cognom" --codi=402 --include_holidays=True --feed=True
```

Calendari per assignatura concreta (format centre/codi):

```
python calendari_professorat.py fes_web_calendari --name="103/103815" --codi=402
```

## Paràmetres principals

Paràmetres habituals a main:

- `name`: nom del professor, diversos noms separats per punt i coma, o format centre/codi per assignatura.
- `codi`: codi de departament (per exemple 402 Matemàtiques).
- `out_ics`: si es genera fitxer ICS.
- `out_html`: si es genera fitxer HTML.
- `outfile`: prefix dels fitxers de sortida.
- `include_holidays`: inclou o exclou festius/no lectius.
- `block_list`: llista de codis d’assignatura a excloure del resultat.

Sobre block_list:

- Accepta llista, enter, string simple o codis separats per comes.
- Exemple: --block_list='["103815","103814"]'

## Ús web amb PHP

El frontend a [calendari_professor.php](calendari_professor.php) crida [calendari_professorat.py](calendari_professorat.py).

Flux principal:

1. Usuari obre formulari web.
2. PHP executa `fes_web_calendari` i incrusta l’HTML retornat.
3. Si es demana `feed=true`, PHP retorna `content-type text/calendar`.

Paràmetres web rellevants:

- `nom`: professor o professors (separats per ;), o assignatura en format centre/codi.
- `departament` o `codi`: departament (402, 403, etc.).
- `holidays`: `true` o `false`.
- `feed`: `true` per retornar ICS directament.
- `block`: codis d’assignatura a excloure, admet format separat per comes.

Exemple de feed:

```
https://mat.uab.cat/calendari_professorat?nom=Nom%20Cognom&departament=402&holidays=true&feed=true
```

Exemple amb bloqueig de codis:

```
https://mat.uab.cat/calendari_professorat?nom=Nom%20Cognom&departament=402&holidays=true&feed=true&block=103815,103814
```

## Cache i fitxers de dades

Els scripts mantenen cache a la carpeta definida per CACHED_CALENDARS_DIR (per defecte dins HOME).

Format dels fitxers `.data`:

1. Primera línia: nom complet del professor.
2. Segona línia: nombre d’assignatures.
3. Següents línies: assignatures serialitzades.
4. Resta del fitxer: contingut ICS complet.

Això permet evitar consultes remotes repetides i accelerar respostes web/feed.

## Proves

El projecte inclou proves de consistència de [calendari_professorat.py](calendari_professorat.py).

Executar totes les proves:

```
python -m unittest tests/test_cached_flow_consistency.py tests/test_output_consistency.py -v
```

Què validen:

- Transformació de calendari consistent (events i ICS canònic).
- Lògica de bloqueig i festius.
- Sortida de feed ICS en flux amb cache.

## Codis de departament habituals

- 402: Matemàtiques
- 403: Química
- 404: Física
- 405: Geologia
- 406: Bioquímica i Biologia Molecular
- 407: Biologia Animal, Biologia Vegetal i Ecologia
- 409: Genètica i Microbiologia

## Resolució de problemes

Si no troba professor:

- Verifica el departament correcte.
- Prova amb menys paraules del nom.
- Revisa si existeix cache antiga inconsistent.

Si falla la generació ICS:

- Comprova connectivitat amb els endpoints UAB.
- Reintenta amb `include_holidays=False` per descartar problemes de filtratge.

Si la web no mostra resultats:

- Revisa ruta de Python a [calendari_professor.php](calendari_professor.php).
- Revisa permisos d’escriptura a la carpeta de cache.
- Revisa sortida d’error del proc_open al PHP.
