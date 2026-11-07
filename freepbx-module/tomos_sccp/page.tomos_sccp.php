<?php
if (!defined('FREEPBX_IS_AUTH')) {
    die('No direct script access allowed');
}

$manager = '/usr/local/libexec/tomos-sccp/tomos-sccp-manager.py';
$python = '/usr/bin/python3';
$inventory = [];
$message = '';
$error = '';

if (!is_executable($manager) || !is_executable($python)) {
    $error = 'TomOS provisioning manager is not installed. Re-run the TomOS SCCP installer.';
}

if (session_status() === PHP_SESSION_NONE) {
    session_start();
}
if (empty($_SESSION['tomos_sccp_csrf'])) {
    $_SESSION['tomos_sccp_csrf'] = bin2hex(random_bytes(32));
}
$csrf = $_SESSION['tomos_sccp_csrf'];

function tomos_sccp_command($manager, $python, array $arguments) {
    $parts = [escapeshellarg($python), escapeshellarg($manager)];
    foreach ($arguments as $argument) {
        $parts[] = escapeshellarg((string)$argument);
    }
    $output = [];
    $status = 0;
    exec(implode(' ', $parts) . ' 2>&1', $output, $status);
    return [$status, implode("\n", $output)];
}

function tomos_sccp_post($key, $default = '') {
    return isset($_POST[$key]) && is_string($_POST[$key]) ? trim($_POST[$key]) : $default;
}

function tomos_sccp_h($value) {
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

if ($error === '' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    $postedToken = tomos_sccp_post('csrf');
    if (!hash_equals($csrf, $postedToken)) {
        $error = 'The form security token expired. Refresh the page and try again.';
    } else {
        $action = tomos_sccp_post('action');
        $arguments = [];
        if ($action === 'add' || $action === 'update') {
            $mac = strtoupper(str_replace([':', '-'], '', tomos_sccp_post('mac')));
            $fields = [
                '--vendor' => tomos_sccp_post('vendor', 'cisco'),
                '--model' => tomos_sccp_post('model'),
                '--template-family' => tomos_sccp_post('template_family'),
                '--extension' => tomos_sccp_post('extension'),
                '--description' => tomos_sccp_post('description'),
                '--label' => tomos_sccp_post('label'),
                '--cid-name' => tomos_sccp_post('cid_name'),
                '--cid-num' => tomos_sccp_post('cid_num'),
                '--context' => tomos_sccp_post('context', 'from-internal-xfer'),
            ];
            if ($action === 'add') {
                $arguments = ['device', 'add', '--mac', $mac];
                foreach ($fields as $flag => $value) {
                    if ($value !== '') {
                        $arguments[] = $flag;
                        $arguments[] = $value;
                    }
                }
                $dhcp = tomos_sccp_post('dhcp_address');
                if ($dhcp !== '') {
                    $arguments[] = '--dhcp-address';
                    $arguments[] = $dhcp;
                }
            } else {
                $arguments = ['device', 'update', '--mac', $mac];
                foreach ($fields as $flag => $value) {
                    if ($value !== '') {
                        $arguments[] = $flag;
                        $arguments[] = $value;
                    }
                }
                // An empty DHCP field explicitly clears the reservation.
                $arguments[] = '--dhcp-address';
                $arguments[] = tomos_sccp_post('dhcp_address');
            }
        } elseif ($action === 'delete') {
            $arguments = ['device', 'remove', '--mac', strtoupper(str_replace([':', '-'], '', tomos_sccp_post('mac'))), '--confirm'];
        } else {
            $error = 'Unknown manager action.';
        }

        if ($error === '') {
            [$status, $output] = tomos_sccp_command($manager, $python, $arguments);
            if ($status === 0) {
                $message = $output !== '' ? $output : 'Inventory updated.';
            } else {
                $error = $output !== '' ? $output : 'The provisioning manager rejected the request.';
            }
        }
    }
}

if ($error === '' || is_executable($manager)) {
    [$status, $output] = tomos_sccp_command($manager, $python, ['device', 'list', '--json']);
    if ($status === 0) {
        $decoded = json_decode($output, true);
        if (is_array($decoded)) {
            $inventory = $decoded;
        } else {
            $error = 'The inventory returned invalid JSON. Check the TomOS manager installation.';
        }
    } elseif ($error === '') {
        $error = $output;
    }
}

$families = [
    '69xx' => 'Cisco 69xx',
    '791x' => 'Cisco 791x',
    '7925' => 'Cisco 7925',
    '7937' => 'Cisco 7937',
    '7940_7960' => 'Cisco 7940 / 7960',
    '796x' => 'Cisco 796x',
    '797x' => 'Cisco 797x',
    '797x_extended' => 'Cisco 797x extended',
];
?>
<div class="container-fluid">
  <h1>TomOS SCCP Manager</h1>
  <p>Phone inventory is stored in the TomOS provisioning database. Changes made here are immediately visible to the TomOS command-line manager.</p>
  <?php if ($message !== ''): ?><div class="alert alert-success"><?php echo tomos_sccp_h($message); ?></div><?php endif; ?>
  <?php if ($error !== ''): ?><div class="alert alert-danger"><?php echo tomos_sccp_h($error); ?></div><?php endif; ?>

  <h2>Registered phones</h2>
  <div class="table-responsive">
    <table class="table table-striped">
      <thead><tr><th>MAC</th><th>Model</th><th>Template</th><th>Extension</th><th>Description</th><th>DHCP address</th><th>Actions</th></tr></thead>
      <tbody>
      <?php foreach ($inventory as $phone): ?>
        <tr>
          <td><?php echo tomos_sccp_h($phone['mac'] ?? ''); ?></td>
          <td><?php echo tomos_sccp_h($phone['model_number'] ?? ''); ?></td>
          <td><?php echo tomos_sccp_h($phone['template_family'] ?? ''); ?></td>
          <td><?php echo tomos_sccp_h($phone['extension'] ?? ''); ?></td>
          <td><?php echo tomos_sccp_h($phone['description'] ?? ''); ?></td>
          <td><?php echo tomos_sccp_h($phone['dhcp_address'] ?? ''); ?></td>
          <td>
            <details>
              <summary>Edit</summary>
              <form method="post" class="form-horizontal">
                <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>">
                <input type="hidden" name="action" value="update">
                <input type="hidden" name="mac" value="<?php echo tomos_sccp_h($phone['mac'] ?? ''); ?>">
                <?php foreach ([
                  'model' => 'Model number', 'extension' => 'Extension', 'description' => 'Description',
                  'label' => 'Line label', 'cid_name' => 'Caller ID name', 'cid_num' => 'Caller ID number',
                  'context' => 'Dialplan context', 'dhcp_address' => 'DHCP IPv4 address'
                ] as $field => $label): ?>
                  <label><?php echo tomos_sccp_h($label); ?>
                    <input class="form-control" name="<?php echo tomos_sccp_h($field); ?>" value="<?php echo tomos_sccp_h($phone[$field] ?? ''); ?>">
                  </label>
                <?php endforeach; ?>
                <label>Template family
                  <select class="form-control" name="template_family">
                    <?php foreach ($families as $slug => $label): ?>
                      <option value="<?php echo tomos_sccp_h($slug); ?>" <?php echo (($phone['template_family'] ?? '') === $slug) ? 'selected' : ''; ?>><?php echo tomos_sccp_h($label); ?></option>
                    <?php endforeach; ?>
                  </select>
                </label>
                <input type="hidden" name="vendor" value="cisco">
                <button class="btn btn-primary" type="submit">Save phone</button>
              </form>
            </details>
            <form method="post" onsubmit="return confirm('Remove this phone from the TomOS inventory?');">
              <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>">
              <input type="hidden" name="action" value="delete">
              <input type="hidden" name="mac" value="<?php echo tomos_sccp_h($phone['mac'] ?? ''); ?>">
              <button class="btn btn-danger btn-xs" type="submit">Remove</button>
            </form>
          </td>
        </tr>
      <?php endforeach; ?>
      <?php if (!$inventory): ?><tr><td colspan="7">No phones in the TomOS inventory yet.</td></tr><?php endif; ?>
      </tbody>
    </table>
  </div>

  <h2>Add Cisco phone</h2>
  <form method="post" class="form-horizontal">
    <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>">
    <input type="hidden" name="action" value="add">
    <div class="row">
      <div class="col-md-3"><label>MAC address<input class="form-control" name="mac" required placeholder="001122AABBCC"></label></div>
      <div class="col-md-2"><label>Model number<input class="form-control" name="model" required placeholder="7960"></label></div>
      <div class="col-md-3"><label>Template family<select class="form-control" name="template_family"><?php foreach ($families as $slug => $label): ?><option value="<?php echo tomos_sccp_h($slug); ?>"><?php echo tomos_sccp_h($label); ?></option><?php endforeach; ?></select></label></div>
      <div class="col-md-2"><label>Extension<input class="form-control" name="extension" required></label></div>
      <div class="col-md-2"><label>DHCP IPv4<input class="form-control" name="dhcp_address"></label></div>
    </div>
    <div class="row">
      <div class="col-md-4"><label>Description<input class="form-control" name="description" required></label></div>
      <div class="col-md-2"><label>Line label<input class="form-control" name="label"></label></div>
      <div class="col-md-2"><label>Caller ID name<input class="form-control" name="cid_name"></label></div>
      <div class="col-md-2"><label>Caller ID number<input class="form-control" name="cid_num"></label></div>
      <div class="col-md-2"><label>Context<input class="form-control" name="context" value="from-internal-xfer"></label></div>
    </div>
    <input type="hidden" name="vendor" value="cisco">
    <button class="btn btn-primary" type="submit">Add phone to shared inventory</button>
  </form>
</div>
