<?php
$result = null;
$k_value = null;
$ell_result = null;
$result_success = false;
$html_output = null;
$output_file = null;
$output_scp = null;
$return_var = null;

$departaments = [
  402 => "Matemàtiques",
  403 => "Química",
  404 => "Física",
  405 => "Geologia",
  406 => "Bioquímica i de Biologia Molecular",
  407 => "Biologia Animal, de Biologia Vegetal i d'Ecologia",
  409 => "Genètica i de Microbiologia"];

//  411 => "Departament d'Economia Aplicada",
//  412 => "Departament d'Economia i d'Història Econòmica",
//  415 => "Departament de Ciències Morfològiques",
//  416 => "Departament de Cirurgia",
//  417 => "Departament de Medicina",
//  421 => "Departament de Didàctica de l'Expressió Musical, Plàstica i Corporal",
//  422 => "Departament de Didàctica de la Llengua i la Literatura i de les Ciències Socials",
//  423 => "Departament de Didàctica de la Matemàtica i de les Ciències Experimentals",
//  426 => "Departament d'Història Moderna i Contemporània",
//  427 => "Departament de Filologia Catalana",
//  428 => "Departament de Filologia Espanyola",
//  429 => "Departament de Filologia Anglesa i de Germanística",
//  430 => "Departament de Filologia Francesa i Romànica",
//  431 => "Departament de Geografia",
//  432 => "Departament de Pedagogia Aplicada",
//  433 => "Departament de Ciència Política i de Dret Públic",
// 434 => "Departament de Sociologia",
//  436 => "Departament de Filosofia",
//  438 => "Departament de Dret Privat",
//  439 => "Departament de Dret Públic i de Ciències Historicojurídiques",
//  452 => "Departament de Psicobiologia i de Metodologia de les Ciències de la Salut",
//  454 => "Departament de Ciències de l'Antiguitat i de l'Edat Mitjana",
//  455 => "Departament de Psiquiatria i de Medicina Legal",
//  456 => "Departament de Biologia Cel·lular, de Fisiologia i d'Immunologia",
//  457 => "Departament de Sanitat i d'Anatomia Animals",
//  458 => "Departament de Ciència Animal i dels Aliments",
//  459 => "Departament de Medicina i Cirurgia Animal",
//  461 => "Departament de Telecomunicació i d'Enginyeria de Sistemes",
//  462 => "Departament de Farmacologia, de Terapèutica i de Toxicologia",
//  463 => "Departament d'Enginyeria Electrònica",
//  464 => "Departament de Psicologia Bàsica, Evolutiva i de l'Educació",
//  465 => "Departament d'Antropologia Social i Cultural",
//  466 => "Departament de Prehistòria",
//  467 => "Departament de Psicologia Clínica i de la Salut",
//  468 => "Departament de Psicologia Social",
//  469 => "Departament d'Arquitectura de Computadors i Sistemes Operatius",
//  470 => "Departament de Microelectrònica i de Sistemes Electrònics",
//  471 => "Departament de Ciències de la Computació",
//  472 => "Departament d'Enginyeria de la Informació i de les Comunicacions",
//  474 => "Departament d'Art i Musicologia",
//  477 => "Departament de Mitjans, Comunicació i Cultura",
//  478 => "Departament de Periodisme i de Ciències de la Comunicació",
//  479 => "Departament d'Infermeria",
//  483 => "Departament de Publicitat, Relacions Públiques i Comunicació Audiovisual",
//  484 => "Departament de Comunicació Audiovisual i Publicitat",
//  485 => "Departament d'Empresa",
//  492 => "Sense informar en origen (Hominis-Samas-PDS)",
//  2558 => "Departament de Traducció i Interpretació i d'Estudis de l'Àsia Oriental",
//  2634 => "Departament d'Enginyeria Química, Biològica i Ambiental",
//  2825 => "Departament de Pediatria, d'Obstetrícia i Ginecologia i de Medicina Preventiva i Salut Pública",
//  2972 => "Departament de Teories de l'Educació i Pedagogia Social",
//];

$departament = 402; // Default: Departament de Matemàtiques
if (isset($_REQUEST['departament'])) {
  $requested_departament = (int)$_REQUEST['departament'];
  if (array_key_exists($requested_departament, $departaments)) {
    $departament = $requested_departament;
  }
}

function build_block_list_arg($raw_block) {
    $blocks = [];
    foreach ((array)$raw_block as $chunk) {
        foreach (explode(',', (string)$chunk) as $v) {
            $v = trim($v);
            if ($v !== '') $blocks[] = $v;
        }
    }
    if (!$blocks) return '';
    return " --block_list=" . escapeshellarg(json_encode($blocks, JSON_UNESCAPED_UNICODE));
}

if (isset($_GET['nom']) && isset($_GET['feed']) && $_GET['feed'] === 'true') {
    // Return an iCal feed directly by invoking the Python module to emit ICS to stdout
    $nom = $_GET['nom'];
    $block_list_arg = build_block_list_arg($_GET['block'] ?? null);
    
    $safe_nom = escapeshellarg($nom);
    $python_code = "calendari_professor.py fes_feed --name=" . $safe_nom . " --codi=" . $departament . $block_list_arg;
    $output = run_python_code($python_code);
    if ($output['success']) {
        header('Content-Type: text/calendar; charset=utf-8');
        header('Content-Disposition: inline; filename="calendari_professor.ics"');
        echo $output['stdout'];
        exit;
    } else {
        // fall back to showing an error in HTML
        $resultat = "Error generating feed: " . $output['stderr'];
    }
}
// Prefer GET (non-feed) over POST; handle form POST otherwise
elseif (isset($_GET['nom'])) {
  handle_nom_request($_GET['nom'], $departament, $_GET['holidays'] ?? null);
} elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['nom'])) {
  handle_nom_request($_POST['nom'], $_POST['departament'], $_POST['holidays'] ?? null);
}

// Unified request handling for GET/POST 'nom' (excluding feed handling above)
function handle_nom_request($raw_nom, $departament, $holidays_option) {
  global $nom, $resultat;

  $raw_nom = trim((string)$raw_nom);
  if ($raw_nom === '') {
    $resultat = "Invalid input provided.";
    $nom = '';
    return;
  }

  // Value for HTML output
  $nom = htmlspecialchars($raw_nom, ENT_QUOTES, 'UTF-8');

  // Value for the python command (basic sanitization)
  $safe_nom = escapeshellarg($raw_nom);
  $block_list_arg = build_block_list_arg($_REQUEST['block'] ?? null);
  $python_code = "calendari_professor.py fes_web_calendari --name=" . $safe_nom . " --codi=" . $departament . ($holidays_option === 'true' ? " --include_holidays=True" : " --include_holidays=False") . $block_list_arg;
  $output = run_python_code($python_code);
  $resultat = $output['success'] ? $output['stdout'] : "Error: " . $output['stderr'];
}


// Helper function
function run_python_code($code) {
    $cmd = "/home/masdeu/miniforge3/bin/python $code";

    $process = proc_open($cmd, [['pipe','r'], ['pipe','w'], ['pipe','w']], $pipes);

    if (!is_resource($process)) {
        return ['success' => false, 'stdout' => '', 'stderr' => 'Failed to start process.'];
    }

    fclose($pipes[0]);
    $stdout = stream_get_contents($pipes[1]);
    fclose($pipes[1]);

    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[2]);

    $return_value = proc_close($process);

    return [
        'success' => $return_value === 0,
        'stdout' => trim($stdout),
        'stderr' => trim($stderr) . trim($stdout)
    ];
}
?>


<!DOCTYPE html>
<html lang="en">
<head>
		<link rel="shortcut icon" href="https://www.uab.cat/Xcelerate/WAI/img/simbol.png?v=4.0.0" />
    <link rel="preload" href="https://mat.uab.cat/~masdeu/teaching/misc/MonaSans-Black.woff2" as="Mona Sans" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="https://www.uab.cat/Xcelerate/WAI/css/sites/departament.css?v=4.0.0" />
    <link rel="stylesheet" href="https://www.uab.cat/Xcelerate/WAI/css/vendor/owl/owl.carousel.min.css?v=4.0.0" />
    <noscript>
    <link rel="stylesheet" href="https://www.uab.cat/Xcelerate/WAI/css/noscript.css?v=4.0.0" />
    </noscript>
		<meta charset="UTF-8">
		<meta http-equiv="X-UA-Compatible" content="IE=edge" />
		<meta property="og:title" content="Departament de Matemàtiques" />
		<meta property="og:description" content="Portada" />
		<meta property="og:site_name" content="UAB Barcelona" />
		<meta property="og:image" content="https://www.uab.cat/ca/uab/img/universitat-autonoma-barcelona/logo-xxss.png" />
		<meta property="og:url" content='https://mat.uab.cat/calendari_professorat/'  />
		<meta name="description" content="Portada" />
		<meta name="author" content="UAB - Marc Masdeu" />
		<meta name="robots" content='index, follow' />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
	
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/index.global.min.css">
  <link rel="stylesheet" href="calendari_style.css">
  <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/main.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/locales-all.min.js"></script>
  <script src='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/index.global.min.js'></script>
  <script src="https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Calendari del Professorat</title>
</head>
<body>
  <?php if (!empty($resultat)): ?>
      <?= $resultat ?>
  <?php endif; ?>
  <?php if (!empty($nom)): ?>
    <div class="generated-by">
      Calendari generat per: <strong><?= htmlspecialchars($nom) ?></strong>
    </div>
  <?php else: ?>
      <?php
        // Preserve holidays checkbox state across submissions; default to checked
        $holidays_checked = isset($_REQUEST['holidays']) ? (($_REQUEST['holidays'] === 'true') ? 'checked' : '') : 'checked';
      ?>
      <h2>Calendari del Professorat</h2>
      <form method="POST" action="#resultat">
        <label><small>Nom professor/a o codi assignatura:</small><input type="text" size=50 name="nom" id="nom" placeholder="Carl Friedrich Gauss;Leonard Euler o 103/100088" required></label>
        <label>
          <small>Departament:</small>
          <select name="departament" id="departament">
            <?php foreach ($departaments as $codi_dep => $nom_dep): ?>
              <option value="<?= $codi_dep ?>" <?= ($departament === (int)$codi_dep) ? 'selected' : '' ?>>
                <?= htmlspecialchars($nom_dep, ENT_QUOTES, 'UTF-8') ?>
              </option>
            <?php endforeach; ?>
          </select>
        </label>
        <label><input type="checkbox" id="holidays" name="holidays" value="true" <?php echo $holidays_checked; ?>><small>Incloure festius i no lectius</small></label>
        <button type="submit" name="action" value="genera">Genera</button>
      </form>
      <script>
        $(document).ready(function() {
          const checkResult = () => {
            $.get(window.location.href, function(data) {
              const newResult = $(data).find('#resultat').html();
              if (newResult && newResult.trim() !== '') {
                $('#resultat').html(newResult);
              } else {
                setTimeout(checkResult, 1000); // Check again after 1 second
              }
            });
          };
          checkResult();
        });
      </script>
  <?php endif; ?>

  <footer class="site-footer">
    <p>Copyright &copy; <?= date('Y') ?> Marc Masdeu. Tots els drets reservats.</p>
  </footer>

</body>
</html>
