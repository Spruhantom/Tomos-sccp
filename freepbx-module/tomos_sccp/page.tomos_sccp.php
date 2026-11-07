<?php
if (!defined('FREEPBX_IS_AUTH')) { die('No direct script access allowed'); }

$manager = '/usr/local/libexec/tomos-sccp/tomos-sccp-manager.py';
$python = '/usr/bin/python3';
$inventory = [];
$message = '';
$error = '';
$preview = null;
$sepOutput = '';
$statusData = ['devices' => [], 'raw' => '', 'note' => 'Status not available.'];

if (!is_executable($manager) || !is_executable($python)) {
    $error = 'TomOS provisioning manager is not installed. Re-run the TomOS SCCP installer.';
}
if (session_status() === PHP_SESSION_NONE) { session_start(); }
if (empty($_SESSION['tomos_sccp_csrf'])) { $_SESSION['tomos_sccp_csrf'] = bin2hex(random_bytes(32)); }
$csrf = $_SESSION['tomos_sccp_csrf'];

function tomos_sccp_command($manager, $python, array $arguments) {
    $parts = [escapeshellarg($python), escapeshellarg($manager)];
    foreach ($arguments as $argument) { $parts[] = escapeshellarg((string)$argument); }
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
    if (!hash_equals($csrf, tomos_sccp_post('csrf'))) {
        $error = 'The form security token expired. Refresh the page and try again.';
    } else {
        $action = tomos_sccp_post('action');
        $args = [];
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
                '--context' => tomos_sccp_post('context', 'from-internal-xfer')
            ];
            $args = ['device', $action, '--mac', $mac];
            foreach ($fields as $flag => $value) {
                if ($value !== '') { $args[] = $flag; $args[] = $value; }
            }
            $args[] = '--dhcp-address';
            $args[] = tomos_sccp_post('dhcp_address');
        } elseif ($action === 'delete') {
            $args = ['device', 'remove', '--mac', strtoupper(str_replace([':', '-'], '', tomos_sccp_post('mac'))), '--confirm'];
        } elseif ($action === 'buttons') {
            $args = ['device', 'buttons', '--mac', tomos_sccp_post('mac'), '--extensions', tomos_sccp_post('button_extensions')];
        } elseif ($action === 'line-update') {
            $args = ['line', 'update', '--extension', tomos_sccp_post('line_extension')];
            foreach (['label' => '--label', 'description' => '--description', 'context' => '--context',
                      'cid_name' => '--cid-name', 'cid_num' => '--cid-num'] as $field => $flag) {
                if (tomos_sccp_post($field) !== '') { $args[] = $flag; $args[] = tomos_sccp_post($field); }
            }
        } elseif ($action === 'preview') {
            $args = ['preview'];
        } elseif ($action === 'render') {
            $args = ['render', '--output-dir', tomos_sccp_post('output_dir')];
        } elseif ($action === 'sep-export') {
            $args = ['sep-export', '--pbx-address', tomos_sccp_post('pbx_address'),
                     '--output-dir', tomos_sccp_post('staging_dir')];
            if (tomos_sccp_post('ntp_server') !== '') { $args[] = '--ntp-server'; $args[] = tomos_sccp_post('ntp_server'); }
        } elseif ($action === 'sep-deploy') {
            $args = ['sep-deploy', '--staging-dir', tomos_sccp_post('staging_dir'),
                     '--tftp-root', tomos_sccp_post('tftp_root'),
                     '--approve-sha256', tomos_sccp_post('approve_sha256')];
        } else {
            $error = 'Unknown manager action.';
        }

        if ($error === '') {
            [$result, $output] = tomos_sccp_command($manager, $python, $args);
            if ($result === 0) {
                if ($action === 'preview') {
                    $decoded = json_decode($output, true);
                    if (is_array($decoded)) { $preview = $decoded; }
                    else { $error = 'The preview returned invalid JSON.'; }
                } else {
                    $message = $output !== '' ? $output : 'Operation completed.';
                    if ($action === 'sep-export') { $sepOutput = $output; }
                }
            } else {
                $error = $output !== '' ? $output : 'The provisioning manager rejected the request.';
            }
        }
    }
}

if ($error === '' || is_executable($manager)) {
    [$result, $output] = tomos_sccp_command($manager, $python, ['device', 'list', '--json']);
    if ($result === 0) {
        $decoded = json_decode($output, true);
        if (is_array($decoded)) { $inventory = $decoded; }
        else { $error = 'The inventory returned invalid JSON.'; }
    } elseif ($error === '') { $error = $output; }

    [$status, $statusOutput] = tomos_sccp_command($manager, $python, ['status']);
    if ($status === 0) {
        $decodedStatus = json_decode($statusOutput, true);
        if (is_array($decodedStatus)) { $statusData = $decodedStatus; }
    } else {
        $statusData['note'] = 'Live Asterisk status unavailable: ' . $statusOutput;
    }
}

$families = [
    '69xx' => 'Cisco 69xx', '791x' => 'Cisco 791x', '7925' => 'Cisco 7925',
    '7937' => 'Cisco 7937', '7940_7960' => 'Cisco 7940 / 7960',
    '796x' => 'Cisco 796x', '797x' => 'Cisco 797x', '797x_extended' => 'Cisco 797x extended'
];
$statusByMac = [];
foreach (($statusData['devices'] ?? []) as $state) { $statusByMac[$state['mac']] = $state; }
?>
<div class="container-fluid">
  <h1>TomOS SCCP Manager</h1>
  <p>Phone inventory, line configuration and button assignments are shared with the TomOS CLI.</p>
  <?php if ($message !== ''): ?><div class="alert alert-success"><?php echo tomos_sccp_h($message); ?></div><?php endif; ?>
  <?php if ($error !== ''): ?><div class="alert alert-danger"><?php echo tomos_sccp_h($error); ?></div><?php endif; ?>

  <h2>Live handset status</h2>
  <p><?php echo tomos_sccp_h($statusData['note'] ?? ''); ?></p>
  <div class="table-responsive"><table class="table table-striped">
    <thead><tr><th>Phone</th><th>Extension</th><th>Status</th><th>Asterisk detail</th></tr></thead><tbody>
    <?php foreach ($inventory as $phone): $state = $statusByMac[$phone['mac']] ?? ['state' => 'unknown', 'detail' => 'No status row']; ?>
      <tr><td><?php echo tomos_sccp_h($phone['mac']); ?> — <?php echo tomos_sccp_h($phone['description']); ?></td>
      <td><?php echo tomos_sccp_h($phone['extension']); ?></td>
      <td><?php echo tomos_sccp_h($state['state']); ?></td><td><?php echo tomos_sccp_h($state['detail']); ?></td></tr>
    <?php endforeach; ?>
    <?php if (!$inventory): ?><tr><td colspan="4">No phones in inventory.</td></tr><?php endif; ?>
    </tbody></table></div>
  <form method="post" class="form-inline">
    <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>">
    <input type="hidden" name="action" value="preview">
    <button class="btn btn-default" type="submit">Refresh preview and live status</button>
  </form>

  <h2>Phone inventory, lines and buttons</h2>
  <div class="table-responsive"><table class="table table-striped">
    <thead><tr><th>MAC</th><th>Model</th><th>Template</th><th>Primary line</th><th>Buttons (position order)</th><th>Description</th><th>DHCP</th><th>Actions</th></tr></thead><tbody>
    <?php foreach ($inventory as $phone): ?>
      <tr>
        <td><?php echo tomos_sccp_h($phone['mac']); ?></td><td><?php echo tomos_sccp_h($phone['model_number']); ?></td>
        <td><?php echo tomos_sccp_h($phone['template_family']); ?></td><td><?php echo tomos_sccp_h($phone['extension']); ?></td>
        <td><?php echo tomos_sccp_h($phone['button_extensions'] ?? $phone['extension']); ?></td>
        <td><?php echo tomos_sccp_h($phone['description']); ?></td><td><?php echo tomos_sccp_h($phone['dhcp_address'] ?? ''); ?></td>
        <td>
          <details><summary>Edit phone and primary line</summary>
            <form method="post">
              <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="update">
              <input type="hidden" name="mac" value="<?php echo tomos_sccp_h($phone['mac']); ?>">
              <?php foreach (['model'=>'Model','extension'=>'Primary extension','description'=>'Description','label'=>'Line label','cid_name'=>'Caller ID name','cid_num'=>'Caller ID number','context'=>'Dialplan context','dhcp_address'=>'DHCP IPv4'] as $field=>$label): ?>
                <label><?php echo tomos_sccp_h($label); ?><input class="form-control" name="<?php echo tomos_sccp_h($field); ?>" value="<?php echo tomos_sccp_h($phone[$field] ?? ''); ?>"></label>
              <?php endforeach; ?>
              <label>Template family<select class="form-control" name="template_family"><?php foreach ($families as $slug=>$label): ?>
                <option value="<?php echo tomos_sccp_h($slug); ?>" <?php echo (($phone['template_family'] ?? '') === $slug) ? 'selected' : ''; ?>><?php echo tomos_sccp_h($label); ?></option>
              <?php endforeach; ?></select></label>
              <input type="hidden" name="vendor" value="cisco"><button class="btn btn-primary" type="submit">Save phone</button>
            </form>
          </details>
          <details><summary>Configure line buttons</summary>
            <form method="post">
              <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="buttons">
              <input type="hidden" name="mac" value="<?php echo tomos_sccp_h($phone['mac']); ?>">
              <label>Line extensions in button order (comma-separated)
                <input class="form-control" name="button_extensions" value="<?php echo tomos_sccp_h($phone['button_extensions'] ?? $phone['extension']); ?>">
              </label>
              <button class="btn btn-primary" type="submit">Save buttons</button>
            </form>
          </details>
          <?php foreach (($phone['buttons'] ?? []) as $button): ?>
          <details><summary>Edit line <?php echo tomos_sccp_h($button['line_extension']); ?></summary>
            <form method="post">
              <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="line-update">
              <input type="hidden" name="line_extension" value="<?php echo tomos_sccp_h($button['line_extension']); ?>">
              <?php foreach (['label'=>'Label','description'=>'Description','context'=>'Context','cid_name'=>'Caller ID name','cid_num'=>'Caller ID number'] as $field=>$label): ?>
                <label><?php echo tomos_sccp_h($label); ?><input class="form-control" name="<?php echo tomos_sccp_h($field); ?>" value="<?php echo tomos_sccp_h($button[$field] ?? ''); ?>"></label>
              <?php endforeach; ?>
              <button class="btn btn-primary" type="submit">Save shared line</button>
            </form>
          </details>
          <?php endforeach; ?>
          <form method="post" onsubmit="return confirm('Remove this phone from the TomOS inventory?');">
            <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="delete">
            <input type="hidden" name="mac" value="<?php echo tomos_sccp_h($phone['mac']); ?>"><button class="btn btn-danger btn-xs" type="submit">Remove</button>
          </form>
        </td>
      </tr>
    <?php endforeach; ?>
    </tbody></table></div>

  <h2>Add Cisco phone</h2>
  <form method="post">
    <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="add">
    <div class="row">
      <?php foreach (['mac'=>'MAC address','model'=>'Model number','extension'=>'Primary extension','description'=>'Description','dhcp_address'=>'DHCP IPv4','label'=>'Line label','cid_name'=>'Caller ID name','cid_num'=>'Caller ID number','context'=>'Dialplan context'] as $field=>$label): ?>
        <div class="col-md-3"><label><?php echo tomos_sccp_h($label); ?><input class="form-control" name="<?php echo tomos_sccp_h($field); ?>" <?php echo in_array($field,['mac','model','extension','description'],true) ? 'required' : ''; ?>></label></div>
      <?php endforeach; ?>
      <div class="col-md-3"><label>Template family<select class="form-control" name="template_family"><?php foreach ($families as $slug=>$label): ?><option value="<?php echo tomos_sccp_h($slug); ?>"><?php echo tomos_sccp_h($label); ?></option><?php endforeach; ?></select></label></div>
    </div>
    <input type="hidden" name="vendor" value="cisco"><button class="btn btn-primary" type="submit">Add phone</button>
  </form>

  <h2>Provisioning preview and file generation</h2>
  <p>Preview renders into a temporary directory and does not change live Asterisk configuration.</p>
  <form method="post">
    <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="preview">
    <button class="btn btn-default" type="submit">Generate preview</button>
  </form>
  <?php if (is_array($preview)): ?>
    <p><?php echo tomos_sccp_h($preview['summary'] ?? 'Preview ready'); ?></p>
    <?php foreach (($preview['files'] ?? []) as $filename=>$contents): ?>
      <h4><?php echo tomos_sccp_h($filename); ?></h4><pre style="max-height:360px;overflow:auto"><?php echo tomos_sccp_h($contents); ?></pre>
    <?php endforeach; ?>
  <?php endif; ?>
  <form method="post">
    <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="render">
    <label>Staging output directory<input class="form-control" name="output_dir" value="/var/tmp/tomos-sccp-generated" required></label>
    <button class="btn btn-primary" type="submit">Generate reviewed Asterisk files</button>
  </form>

  <h2>SEP XML export and reviewed TFTP deployment</h2>
  <form method="post">
    <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="sep-export">
    <label>Phone-reachable PBX IPv4<input class="form-control" name="pbx_address" placeholder="192.168.10.5" required></label>
    <label>Optional NTP IPv4<input class="form-control" name="ntp_server"></label>
    <label>SEP staging directory<input class="form-control" name="staging_dir" value="/var/tmp/tomos-sccp-tftp-review" required></label>
    <button class="btn btn-primary" type="submit">Export SEP XML for review</button>
  </form>
  <p>Review the generated XML and manifest. Copy the printed SHA-256 approval value into the deployment form only after reviewing the files.</p>
  <form method="post">
    <input type="hidden" name="csrf" value="<?php echo tomos_sccp_h($csrf); ?>"><input type="hidden" name="action" value="sep-deploy">
    <label>Reviewed staging directory<input class="form-control" name="staging_dir" value="/var/tmp/tomos-sccp-tftp-review" required></label>
    <label>Existing TFTP root<input class="form-control" name="tftp_root" placeholder="/srv/tftp" required></label>
    <label>Approved manifest SHA-256<input class="form-control" name="approve_sha256" pattern="[a-f0-9]{64}" required></label>
    <button class="btn btn-danger" type="submit" onclick="return confirm('Deploy the reviewed SEP XML files to this TFTP root?');">Deploy approved SEP files</button>
  </form>
</div>
