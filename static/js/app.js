// MQTT Music Visualiser - Main Application JavaScript

const socket = io();
const freqPresets = {
  'sub_bass': {min: 20, max: 60, name: 'Sub Bass'},
  'bass': {min: 60, max: 250, name: 'Bass'},
  'low_mid': {min: 250, max: 500, name: 'Low Mid'},
  'mid': {min: 500, max: 2000, name: 'Mid'},
  'high_mid': {min: 2000, max: 4000, name: 'High Mid'},
  'presence': {min: 4000, max: 6000, name: 'Presence'},
  'brilliance': {min: 6000, max: 20000, name: 'Brilliance'},
  'full': {min: 20, max: 20000, name: 'Full'}
};

let currentFreqRanges = [];
let deviceStates = {}; // Track current state of each device
let reconnectInterval = null;
let isReconnecting = false;

// WebSocket event handlers
socket.on('log', (data) => {
  const log = document.getElementById('log-container');
  const entry = document.createElement('div');
  entry.className = `log-entry log-${data.level}`;
  const timestamp = new Date(data.timestamp * 1000).toLocaleTimeString();
  entry.textContent = `[${timestamp}] ${data.message}`;
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
  
  while (log.children.length > 100) {
    log.removeChild(log.firstChild);
  }
});

socket.on('device_state', (data) => {
  deviceStates[data.device_id] = data;
  updateDeviceCircle(data.device_id, data);
});

socket.on('devices_updated', loadDevices);

// Audio spectrum visualization
socket.on('audio_spectrum', (data) => {
  drawSpectrum(data.spectrum);
});

// Socket connection status handlers
socket.on('connect', () => {
  console.log('WebSocket connected');
  if (isReconnecting) {
    showReconnectStatus('✅ Reconnected! Reloading...', 'success');
    setTimeout(() => {
      window.location.reload();
    }, 1000);
  }
});

socket.on('disconnect', () => {
  console.log('WebSocket disconnected');
  if (isReconnecting) {
    showReconnectStatus('🔄 Waiting for server...', 'waiting');
  }
});

// Reconnection polling functions
function showReconnectStatus(message, type) {
  let overlay = document.getElementById('reconnect-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'reconnect-overlay';
    overlay.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0, 0, 0, 0.9);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 10000;
      flex-direction: column;
      gap: 20px;
    `;
    document.body.appendChild(overlay);
  }
  
  const colors = {
    'waiting': '#ffaa00',
    'success': '#00ff88',
    'error': '#ff4444'
  };
  
  overlay.innerHTML = `
    <div style="font-size: 48px;">${type === 'waiting' ? '🔄' : type === 'success' ? '✅' : '❌'}</div>
    <div style="font-size: 24px; color: ${colors[type] || '#fff'}; font-weight: bold;">${message}</div>
    <div style="font-size: 14px; color: #888;">
      ${type === 'waiting' ? 'Polling every 2 seconds...' : ''}
    </div>
  `;
}

function hideReconnectStatus() {
  const overlay = document.getElementById('reconnect-overlay');
  if (overlay) {
    overlay.remove();
  }
}

function startReconnectPolling() {
  isReconnecting = true;
  showReconnectStatus('🔄 Server restarting...', 'waiting');
  
  // Poll the server every 2 seconds
  reconnectInterval = setInterval(() => {
    fetch('/api/stats')
      .then(r => {
        if (r.ok) {
          clearInterval(reconnectInterval);
          reconnectInterval = null;
          showReconnectStatus('✅ Server is back online! Reloading...', 'success');
          setTimeout(() => {
            window.location.reload();
          }, 1000);
        }
      })
      .catch(() => {
        // Server still down, keep polling
        console.log('Server not ready yet, continuing to poll...');
      });
  }, 2000);
}

// Update device circle visual
function updateDeviceCircle(deviceId, state) {
  const circle = document.getElementById(`circle-${deviceId}`);
  if (!circle) return;
  
  if (state.state === 'flash' || state.state === 'on') {
    circle.style.backgroundColor = state.hex;
    circle.style.borderColor = state.hex;
    
    if (state.state === 'flash') {
      circle.classList.add('flash');
      setTimeout(() => circle.classList.remove('flash'), 300);
    }
  } else if (state.state === 'off') {
    circle.style.backgroundColor = '#1a1a1a';
    circle.style.borderColor = '#333';
  }
}

// Control functions
function toggleSystem() {
  const btn = document.getElementById('toggle-btn');
  const isRunning = btn.classList.contains('running');
  
  const endpoint = isRunning ? '/api/stop' : '/api/start';
  
  btn.disabled = true;
  fetch(endpoint, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      updateToggleButton(data.running);
      btn.disabled = false;
    })
    .catch(err => {
      console.error('Toggle failed:', err);
      btn.disabled = false;
    });
}

function updateToggleButton(isRunning) {
  const btn = document.getElementById('toggle-btn');
  if (isRunning) {
    btn.classList.add('running');
    btn.textContent = '⏹ Stop';
  } else {
    btn.classList.remove('running');
    btn.textContent = '▶ Start';
  }
}

function updateConfig() {
  const debug = document.getElementById('debug').checked;
  const interval = parseFloat(document.getElementById('interval').value);
  const threshold = parseFloat(document.getElementById('threshold').value);
  const volume = parseFloat(document.getElementById('volume').value);
  const flash = parseFloat(document.getElementById('flash').value);
  const flashGuardEnabled = document.getElementById('flash-guard').checked;
  
  document.getElementById('interval-val').textContent = interval.toFixed(2);
  document.getElementById('threshold-val').textContent = threshold.toFixed(3);
  document.getElementById('volume-val').textContent = volume.toFixed(3);
  document.getElementById('flash-val').textContent = flash.toFixed(1);
  
  fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      debug: debug,
      min_publish_interval: interval,
      beat_threshold: threshold,
      min_volume: volume,
      flash_duration: flash,
      flash_guard_enabled: flashGuardEnabled
    })
  });
}

function saveConfigToFile() {
  const btn = event.target;
  const originalText = btn.textContent;
  
  btn.disabled = true;
  btn.textContent = '💾 Saving...';
  
  fetch('/api/config/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'saved') {
      btn.textContent = '✅ Saved!';
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 2000);
    } else {
      btn.textContent = '❌ Error';
      console.error('Save error:', data.error);
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 2000);
    }
  })
  .catch(err => {
    btn.textContent = '❌ Failed';
    console.error('Save failed:', err);
    setTimeout(() => {
      btn.textContent = originalText;
      btn.disabled = false;
    }, 2000);
  });
}

function updateMQTTSettings() {
  const btn = event.target;
  const originalText = btn.textContent;
  
  const host = document.getElementById('mqtt-host').value;
  const port = document.getElementById('mqtt-port').value;
  const username = document.getElementById('mqtt-username').value;
  const password = document.getElementById('mqtt-password').value;
  
  if (!host || !port) {
    alert('Host and Port are required');
    return;
  }
  
  if (!confirm('Changing MQTT settings requires restarting the application.\n\nThe page will automatically reconnect when the server is back online.\n\nContinue?')) {
    return;
  }
  
  btn.disabled = true;
  btn.textContent = '⏳ Saving...';
  
  fetch('/api/config/mqtt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host, port, username, password })
  })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'updated') {
      btn.textContent = '✅ Saved! Restart app now';
      alert('MQTT settings saved to config.yaml.\n\nPlease restart the application now.\n\nThe page will automatically reconnect when the server is back online.');
      
      // Start polling for reconnection
      setTimeout(() => {
        startReconnectPolling();
      }, 2000);
    } else {
      btn.textContent = '❌ Error';
      alert('Error: ' + (data.error || 'Unknown error'));
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 2000);
    }
  })
  .catch(err => {
    btn.textContent = '❌ Failed';
    alert('Failed to update MQTT settings: ' + err.message);
    setTimeout(() => {
      btn.textContent = originalText;
      btn.disabled = false;
    }, 2000);
  });
}

function updateAudioSettings() {
  const btn = event.target;
  const originalText = btn.textContent;
  
  const bufferSize = document.getElementById('audio-buffer-size').value;
  const sampleRate = document.getElementById('audio-sample-rate').value;
  const channels = document.getElementById('audio-channels').value;
  
  if (!confirm('Changing audio settings requires restarting the application.\n\nThe page will automatically reconnect when the server is back online.\n\nContinue?')) {
    return;
  }
  
  btn.disabled = true;
  btn.textContent = '⏳ Saving...';
  
  fetch('/api/config/audio', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 
      buffer_size: bufferSize, 
      sample_rate: sampleRate, 
      channels: channels 
    })
  })
  .then(r => r.json())
  .then(data => {
    if (data.status === 'updated') {
      btn.textContent = '✅ Saved! Restart app now';
      alert('Audio settings saved to config.yaml.\n\nPlease restart the application now.\n\nThe page will automatically reconnect when the server is back online.');
      
      // Start polling for reconnection
      setTimeout(() => {
        startReconnectPolling();
      }, 2000);
    } else {
      btn.textContent = '❌ Error';
      alert('Error: ' + (data.error || 'Unknown error'));
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 2000);
    }
  })
  .catch(err => {
    btn.textContent = '❌ Failed';
    alert('Failed to update audio settings: ' + err.message);
    setTimeout(() => {
      btn.textContent = originalText;
      btn.disabled = false;
    }, 2000);
  });
}

function loadDevices() {
  fetch('/api/devices')
    .then(r => r.json())
    .then(devices => {
      // Update visual circles
      const visual = document.getElementById('devices-visual');
      if (devices.length === 0) {
        visual.innerHTML = '<p style="color: #888;">No devices configured</p>';
      } else {
        visual.innerHTML = devices.filter(d => d.enabled).map(d => {
          const freqText = d.freq_ranges.map(r => {
            // Check if it matches a preset
            for (const [key, preset] of Object.entries(freqPresets)) {
              if (preset.min === r.min && preset.max === r.max) {
                return preset.name;
              }
            }
            return `${r.min}-${r.max}Hz`;
          }).join(', ');
          
          return `
            <div class="device-circle">
              ${d.mode === 'flash' ? '<div class="circle-mode flash-mode">FLASH</div>' : '<div class="circle-mode">COLOUR</div>'}
              <div class="circle" id="circle-${d.id}">
                <div class="circle-name">${d.name}</div>
                <div class="circle-freq">${freqText}</div>
              </div>
            </div>
          `;
        }).join('');
      }
      
      // Update device list
      const list = document.getElementById('devices-list');
      if (devices.length === 0) {
        list.innerHTML = '<p style="color: #888;">No devices configured. Click "Add Device" to get started.</p>';
        return;
      }
      
      list.innerHTML = devices.map(d => {
        const freqText = d.freq_ranges.map(r => {
          for (const [key, preset] of Object.entries(freqPresets)) {
            if (preset.min === r.min && preset.max === r.max) {
              return `<span style="color: #00ff88;">${preset.name}</span>`;
            }
          }
          return `${r.min}-${r.max}Hz`;
        }).join(', ');
        
        return `
          <div class="device-card ${d.enabled ? '' : 'disabled'}">
            <div class="device-header">
              <div class="device-name">${d.name} ${d.enabled ? '' : '(Disabled)'}</div>
              <div class="device-controls">
                <button class="btn-edit" onclick="editDevice('${d.id}')">✎ Edit</button>
                <button class="btn-delete" onclick="deleteDevice('${d.id}')">🗑</button>
              </div>
            </div>
            <div class="device-info">
              <strong>Topic:</strong> ${d.topic}<br>
              <strong>Type:</strong> ${d.type}<br>
              <strong>Brightness:</strong> ${d.brightness || 155}<br>
              <strong>Mode:</strong> ${d.mode === 'flash' ? '⚡ Flash' : '🌈 Reactive'}<br>
              <strong>Frequency:</strong> ${freqText}
            </div>
          </div>
        `;
      }).join('');
    });
}

function showAddDevice() {
  document.getElementById('modal-title').textContent = 'Add Device';
  document.getElementById('device-form').reset();
  document.getElementById('device-id').value = '';
  document.getElementById('device-enabled').checked = true;
  document.getElementById('device-brightness').value = 155;
  document.getElementById('device-brightness-val').textContent = '155';
  document.getElementById('device-flash-cooldown').value = 0;
  document.getElementById('device-flash-cooldown-val').textContent = '0.0';
  document.querySelector('input[name="mode"][value="reactive"]').checked = true;
  document.getElementById('flash-colour-section').style.display = 'none';
  document.getElementById('flash-random').checked = false;
  document.getElementById('flash-colour-picker-section').style.display = 'block';
  currentFreqRanges = [];
  
  // Uncheck all frequency toggles
  document.querySelectorAll('.freq-toggles input[type="checkbox"]').forEach(cb => {
    cb.checked = false;
  });
  
  renderFreqRanges();
  document.getElementById('device-modal').classList.add('show');
}

function editDevice(id) {
  fetch('/api/devices')
    .then(r => r.json())
    .then(devices => {
      const device = devices.find(d => d.id === id);
      if (!device) return;
      
      document.getElementById('modal-title').textContent = 'Edit Device';
      document.getElementById('device-id').value = device.id;
      document.getElementById('device-name').value = device.name;
      document.getElementById('device-topic').value = device.topic;
      document.getElementById('device-type').value = device.type;
      document.getElementById('device-enabled').checked = device.enabled;
      const brightness = device.brightness || 155;
      document.getElementById('device-brightness').value = brightness;
      document.getElementById('device-brightness-val').textContent = brightness;
      const flashCooldown = device.flash_cooldown || 0;
      document.getElementById('device-flash-cooldown').value = flashCooldown;
      document.getElementById('device-flash-cooldown-val').textContent = flashCooldown.toFixed(1);
      
      document.querySelector(`input[name="mode"][value="${device.mode}"]`).checked = true;
      document.getElementById('flash-colour-section').style.display = device.mode === 'flash' ? 'block' : 'none';
      
      // Set flash random checkbox
      const flashRandom = device.flash_random || false;
      document.getElementById('flash-random').checked = flashRandom;
      document.getElementById('flash-colour-picker-section').style.display = flashRandom ? 'none' : 'block';
      
      if (device.flash_colour) {
        document.getElementById('flash-colour-rgb').value = device.flash_colour;
        const hex = rgbToHex(device.flash_colour);
        document.getElementById('flash-colour-picker').value = hex;
      }
      
      currentFreqRanges = device.freq_ranges || [];
      
      // Update toggle checkboxes based on device frequency ranges
      document.querySelectorAll('.freq-toggles input[type="checkbox"]').forEach(cb => {
        cb.checked = false;
      });
      
      // Check toggles that match presets
      const nonPresetRanges = [];
      currentFreqRanges.forEach(range => {
        let matchedPreset = false;
        for (const [key, preset] of Object.entries(freqPresets)) {
          if (preset.min === range.min && preset.max === range.max) {
            const checkbox = document.querySelector(`.freq-toggles input[value="${key}"]`);
            if (checkbox) checkbox.checked = true;
            matchedPreset = true;
            break;
          }
        }
        if (!matchedPreset) {
          nonPresetRanges.push(range);
        }
      });
      
      // Only custom ranges in the advanced section
      currentFreqRanges = nonPresetRanges;
      
      renderFreqRanges();
      document.getElementById('device-modal').classList.add('show');
    });
}

function deleteDevice(id) {
  if (!confirm('Delete this device?')) return;
  fetch(`/api/devices/${id}`, { method: 'DELETE' })
    .then(() => loadDevices());
}

function closeModal() {
  document.getElementById('device-modal').classList.remove('show');
}

function addFreqRange() {
  currentFreqRanges.push({min: 20, max: 20000});
  renderFreqRanges();
}

function removeFreqRange(index) {
  currentFreqRanges.splice(index, 1);
  renderFreqRanges();
}

function renderFreqRanges() {
  const container = document.getElementById('freq-ranges-list');
  container.innerHTML = currentFreqRanges.map((range, index) => `
    <div class="freq-range-item">
      <input type="number" value="${range.min}" min="20" max="20000" 
             onchange="currentFreqRanges[${index}].min = parseInt(this.value)" 
             placeholder="Min Hz">
      <span>to</span>
      <input type="number" value="${range.max}" min="20" max="20000" 
             onchange="currentFreqRanges[${index}].max = parseInt(this.value)"
             placeholder="Max Hz">
      <button type="button" onclick="removeFreqRange(${index})">✕</button>
    </div>
  `).join('');
}

function rgbToHex(rgb) {
  const parts = rgb.split(',').map(p => parseInt(p.trim()));
  return '#' + parts.map(p => p.toString(16).padStart(2, '0')).join('');
}

function hexToRgb(hex) {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result ? 
    `${parseInt(result[1], 16)},${parseInt(result[2], 16)},${parseInt(result[3], 16)}` : 
    '255,255,255';
}

// Mode change handler
document.addEventListener('change', (e) => {
  if (e.target.name === 'mode') {
    const flashSection = document.getElementById('flash-colour-section');
    flashSection.style.display = e.target.value === 'flash' ? 'block' : 'none';
  }
});

// Toggle flash colour picker based on random checkbox
function toggleFlashColourPicker() {
  const flashRandom = document.getElementById('flash-random').checked;
  const pickerSection = document.getElementById('flash-colour-picker-section');
  pickerSection.style.display = flashRandom ? 'none' : 'block';
}

function updateDeviceBrightness() {
  const brightness = document.getElementById('device-brightness').value;
  document.getElementById('device-brightness-val').textContent = brightness;
}

function updateDeviceFlashCooldown() {
  const cooldown = parseFloat(document.getElementById('device-flash-cooldown').value);
  document.getElementById('device-flash-cooldown-val').textContent = cooldown.toFixed(1);
}

// Colour picker sync
document.addEventListener('input', (e) => {
  if (e.target.id === 'flash-colour-picker') {
    document.getElementById('flash-colour-rgb').value = hexToRgb(e.target.value);
  } else if (e.target.id === 'flash-colour-rgb') {
    try {
      const hex = rgbToHex(e.target.value);
      document.getElementById('flash-colour-picker').value = hex;
    } catch (err) {}
  }
});

function saveDevice(e) {
  e.preventDefault();
  
  const id = document.getElementById('device-id').value;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const flashRandom = document.getElementById('flash-random').checked;
  
  // Collect frequency ranges from toggles
  const freqRanges = [];
  
  // Get checked preset toggles
  document.querySelectorAll('.freq-toggles input[type="checkbox"]:checked').forEach(cb => {
    const preset = freqPresets[cb.value];
    if (preset) {
      freqRanges.push({min: preset.min, max: preset.max});
    }
  });
  
  // Add custom ranges
  freqRanges.push(...currentFreqRanges);
  
  // If no ranges selected, default to full range
  if (freqRanges.length === 0) {
    freqRanges.push({min: 20, max: 20000});
  }
  
  const data = {
    id: id || undefined,
    name: document.getElementById('device-name').value,
    topic: document.getElementById('device-topic').value,
    type: document.getElementById('device-type').value,
    enabled: document.getElementById('device-enabled').checked,
    brightness: parseInt(document.getElementById('device-brightness').value, 10),
    mode: mode,
    flash_colour: mode === 'flash' ? document.getElementById('flash-colour-rgb').value : '255,255,255',
    flash_random: mode === 'flash' ? flashRandom : false,
    flash_cooldown: parseFloat(document.getElementById('device-flash-cooldown').value),
    freq_ranges: freqRanges
  };
  
  const method = id ? 'PUT' : 'POST';
  const url = id ? `/api/devices/${id}` : '/api/devices';
  
  fetch(url, {
    method: method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  .then(r => r.json())
  .then(() => {
    closeModal();
    loadDevices();
  });
}

// Update stats every second
setInterval(() => {
  fetch('/api/stats')
    .then(r => r.json())
    .then(data => {
      document.getElementById('beats').textContent = data.beats_detected;
      document.getElementById('messages').textContent = data.messages_sent;
      document.getElementById('frequency').textContent = Math.round(data.current_frequency);
      document.getElementById('status').textContent = data.running ? 'Running' : 'Stopped';
      updateToggleButton(data.running);
    });
}, 1000);

// Load initial configuration
function loadConfigSettings() {
  fetch('/api/config')
    .then(r => r.json())
    .then(data => {
      // Load MQTT settings
      if (data.mqtt) {
        document.getElementById('mqtt-host').value = data.mqtt.host || '';
        document.getElementById('mqtt-port').value = data.mqtt.port || '';
      }
      
      // Load audio settings
      if (data.audio) {
        document.getElementById('audio-buffer-size').value = data.audio.buffer_size || 2048;
        document.getElementById('audio-sample-rate').value = data.audio.sample_rate || 44100;
        document.getElementById('audio-channels').value = data.audio.channels || 1;
      }
      
      // Load runtime settings
      if (data.runtime) {
        document.getElementById('debug').checked = data.runtime.debug || false;
        document.getElementById('interval').value = data.runtime.min_publish_interval || 0.1;
        document.getElementById('threshold').value = data.runtime.beat_threshold || 0.01;
        document.getElementById('volume').value = data.runtime.min_volume || 0.005;
        document.getElementById('flash').value = data.runtime.flash_duration || 0.3;
        document.getElementById('flash-guard').checked = data.runtime.flash_guard_enabled !== false;
        
        // Update display values
        document.getElementById('interval-val').textContent = (data.runtime.min_publish_interval || 0.1).toFixed(2);
        document.getElementById('threshold-val').textContent = (data.runtime.beat_threshold || 0.01).toFixed(3);
        document.getElementById('volume-val').textContent = (data.runtime.min_volume || 0.005).toFixed(3);
        document.getElementById('flash-val').textContent = (data.runtime.flash_duration || 0.3).toFixed(1);
      }
    })
    .catch(err => console.error('Failed to load config:', err));
}

// Load devices and config on startup
loadDevices();
loadConfigSettings();

// Audio visualization canvas setup
const canvas = document.getElementById('audio-canvas');
const ctx = canvas.getContext('2d');
let lastSpectrum = [];

function drawSpectrum(spectrum) {
  if (!spectrum || spectrum.length === 0) return;
  
  lastSpectrum = spectrum;
  
  // Clear canvas
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  
  // Draw spectrum bars
  const barWidth = canvas.width / spectrum.length;
  const barGap = 1;
  
  for (let i = 0; i < spectrum.length; i++) {
    const value = spectrum[i];
    const barHeight = value * canvas.height * 0.9;
    const x = i * barWidth;
    const y = canvas.height - barHeight;
    
    // Create gradient for bars
    const gradient = ctx.createLinearGradient(0, y, 0, canvas.height);
    gradient.addColorStop(0, '#00ff88');
    gradient.addColorStop(0.5, '#4488ff');
    gradient.addColorStop(1, '#ff4444');
    
    ctx.fillStyle = gradient;
    ctx.fillRect(x, y, barWidth - barGap, barHeight);
  }
  
  // Draw frequency labels
  ctx.fillStyle = '#888';
  ctx.font = '10px monospace';
  ctx.fillText('20 Hz', 5, canvas.height - 5);
  ctx.fillText('Low', canvas.width * 0.25, canvas.height - 5);
  ctx.fillText('Mid', canvas.width * 0.5, canvas.height - 5);
  ctx.fillText('High', canvas.width * 0.75, canvas.height - 5);
}

// Draw initial empty state
drawSpectrum([]);
