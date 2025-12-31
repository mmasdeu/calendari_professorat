<?php
$result = null;
$k_value = null;
$ell_result = null;
$result_success = false;
$html_output = null;
$output_file = null;
$output_scp = null;
$return_var = null;

function make_python_code($nom, $include_holidays = false) {
    return "-m fire calendari_professor.py fes_web_calendari --name=\"" . $nom . "\"" . ($include_holidays ? " --include_holidays=True" : " --include_holidays=False");
};

if (isset($_GET['nom']) && isset($_GET['feed']) && $_GET['feed'] === 'true') {
    // Return an iCal feed directly by invoking the Python module to emit ICS to stdout
    $nom = $_GET['nom'];
    $safe_nom = escapeshellarg($nom);
    $python_code = "calendari_professor.py fes_feed \"" . $safe_nom . "\"";
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

// Unified request handling for GET/POST 'nom' (excluding feed handling above)
function handle_nom_request($raw_nom, $holidays_option) {
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
  $safe_nom = filter_var($raw_nom, FILTER_SANITIZE_STRING);
  $python_code = make_python_code($safe_nom, include_holidays: $holidays_option === 'true');
  $output = run_python_code($python_code);
  $resultat = $output['success'] ? $output['stdout'] : "Error: " . $output['stderr'];
}

// Prefer GET (non-feed) over POST; handle form POST otherwise
if (isset($_GET['nom'])) {
  handle_nom_request($_GET['nom'], $_GET['holidays'] ?? null);
} elseif ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['nom'])) {
  handle_nom_request($_POST['nom'], $_POST['holidays'] ?? null);
}

// Helper function
function run_python_code($code) {
    $cmd = "/home/masdeu/miniforge3/bin/conda run -n base python $code";

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

  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/main.min.css">
  <link rel="stylesheet" href="calendari_style.css">
  <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/main.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/locales-all.min.js"></script>
  <script src='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.20/index.global.min.js'></script>
  <script src="https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"></script>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Calendari del Professor</title>
</head>
<style>
.col {
    background: #f0f0f0; 
    width: 230px; 
    padding: 10px; 
    font-size: 1.5em; 
    word-wrap: break-word; 
}  

  body {
    background-color: white;
    color: black;
  }

  div {
    word-wrap: break-word;         /* All browsers since IE 5.5+ */
    overflow-wrap: break-word;     /* Renamed property in CSS3 draft spec */
    width: 100%;
    white-space: normal; /* Prevents text from overflowing */
  }

  .step-form {
    display: flex;
    flex-direction: column;
    gap: 0.8em;
    margin-top: 1em;
    width: 250px;
  }

  .step-form label {
    font-weight: bold;
    justify-content: center;

  }

  .step-form input,
  .step-form button {
    max-width: 300px;
    justify-content: center;    
  }

  @media (prefers-color-scheme: dark) {
    body {
      background-color: #121212;
      color: #e0e0e0;
    }

    a {
      color: #80cfff;
    }

    input, button {
      background-color: #2c2c2c;
      color: white;
      border: 1px solid #555;
    }
  }
</style>

<body>
    <?php if (!empty($nom)): ?>
    <div style="text-align: center; font-size: 1.2em; margin-bottom: 1em;">
      <strong>Calendari generat per: <?= htmlspecialchars($nom) ?></strong>
    </div>
  <?php else: ?>
      <?php
        // Preserve holidays checkbox state across submissions; default to checked
        $holidays_checked = isset($_REQUEST['holidays']) ? (($_REQUEST['holidays'] === 'true') ? 'checked' : '') : 'checked';
      ?>
      <form method="POST" action="#resultat">
        <label><small>Nom professor/a o codi assignatura:</small><input type="text" size=30 name="nom" id="nom" placeholder="Carl Friedrich Gauss o 103/100088" required></label>
        <label><input type="checkbox" id="holidays" name="holidays" value="true" <?php echo $holidays_checked; ?>><small>Incloure festius i no lectius</small></label>
        <button type="submit" name="action" value="genera">Genera</button>
      </form>
  <?php endif; ?>
  <?php if (!empty($resultat)): ?>
  
        <?= $resultat ?>
        
  <?php endif; ?>
</body>
</html>
