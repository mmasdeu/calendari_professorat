<?php
$result = null;
$k_value = null;
$ell_result = null;
$result_success = false;
$html_output = null;
$output_file = null;
$output_scp = null;
$return_var = null;

function make_python_code($nom) {
    return "-m fire calendari_professor.py fes_web_calendari --name=\"" . $nom . "\"";
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

if (isset($_GET['nom'])) {
    $nom =  $_GET['nom'];
    $python_code = make_python_code($nom);
    // Stream output live to the browser instead of buffering it all
    $output = run_python_code($python_code);
    $resultat = $output['success'] ? $output['stdout'] : "Error: " . $output['stderr'];

}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  $action = $_POST['action'] ?? null;
  
  if ($action === 'genera') {
    $nom = $_POST['nom'] ?? '';
    $python_code = make_python_code($nom);
    // Stream output live to the browser
    $output = run_python_code($python_code);
    $resultat = $output['success'] ? $output['stdout'] : "Error: " . $output['stderr'];
  };
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
  <link rel="stylesheet" href="https://matcha.mizu.sh/matcha.css">
            <link href="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.css" rel="stylesheet">
                <script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/dist/index.global.js">
                </script><script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/main.min.js">
                </script><script src="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.3/locales-all.min.js">
                <script src="https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"></script>
  <meta charset="UTF-8">
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
      <form method="POST" class="step-form" action="#resultat">
        <label for="nom">Introdueix el nom</label>
        <input type="text" name="nom" id="nom" placeholder="Carl Friedrich Gauss" required>
        <button type="submit" name="action" value="genera">Genera</button>
      </form>
  <?php endif; ?>
  <?php if (!empty($resultat)): ?>
        <?= $resultat ?>
        
  <?php endif; ?>
</body>
</html>
