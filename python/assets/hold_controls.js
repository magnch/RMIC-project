(function () {
  const HOLD_INTERVAL_MS = 120;
  const SEND_LOOP_MS = 80;
  const MIN_SEND_GAP_MS = 80;
  const PRECISION_FACTOR = 0.6;
  const KEY_TO_COMMAND = {
    w: 'F',
    arrowup: 'F',
    s: 'B',
    arrowdown: 'B',
    a: 'L',
    arrowleft: 'L',
    d: 'R',
    arrowright: 'R',
  };

  let activeCommand = null;
  let holdIntervalId = null;
  let activeInputSource = null;
  let pressedMovementKeys = [];
  let precisionMode = false;
  let lastSentCommand = null;
  let lastSentSpeed = null;
  let lastSentAtMs = 0;
  let desiredCommand = 'S';
  let desiredSpeed = 0;
  let desiredSource = '-';
  let sendLoopId = null;
  let sendInFlight = false;
  let sendImmediate = false;

  function debugEvent(event, data = {}) {
    const payload = {
      event,
      ts: Date.now(),
      ...data,
    };

    fetch('/debug/client', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {});
  }

  function getBotIp() {
    const ipNode = document.getElementById('bot-ip');
    return ipNode ? ipNode.textContent.trim() : null;
  }

  function getSpeed() {
    const speedNode = document.getElementById('speed-value');
    const syncedValue = speedNode ? speedNode.textContent.trim() : null;
    if (syncedValue) {
      return syncedValue;
    }

    const speedInput = document.getElementById('speed-input');
    const value = speedInput ? String(speedInput.value || '').trim() : null;
    return value || '120';
  }

  function getEffectiveSpeed() {
    const speed = Number.parseInt(getSpeed(), 10);
    if (Number.isNaN(speed)) return 120;
    const clamped = Math.max(0, Math.min(255, speed));
    if (!precisionMode) {
      return clamped;
    }
    return Math.max(0, Math.round(clamped * PRECISION_FACTOR));
  }

  function ensureSendLoop() {
    if (sendLoopId !== null) {
      return;
    }

    sendLoopId = setInterval(() => {
      flushDesiredCommand();
    }, SEND_LOOP_MS);
  }

  function queueDesiredCommand(command, speed, source = '-', immediate = false) {
    desiredCommand = command;
    desiredSpeed = speed;
    desiredSource = source;
    if (immediate) {
      sendImmediate = true;
    }
    ensureSendLoop();
    if (immediate) {
      flushDesiredCommand();
    }
  }

  function flushDesiredCommand() {
    const botIp = getBotIp();
    if (!botIp || botIp === '192.168.x.x') {
      return;
    }

    if (sendInFlight) {
      return;
    }

    const command = desiredCommand;
    const speed = desiredSpeed;

    const now = Date.now();
    if (
      !sendImmediate &&
      command === lastSentCommand &&
      speed === lastSentSpeed &&
      now - lastSentAtMs < MIN_SEND_GAP_MS
    ) {
      debugEvent('send-skip-dedupe', { command, speed, source: desiredSource || '-' });
      return;
    }
    sendImmediate = false;

    const url = '/api/motor';
    sendInFlight = true;
    lastSentCommand = command;
    lastSentSpeed = speed;
    lastSentAtMs = Date.now();
    debugEvent('send-attempt', { command, speed, source: desiredSource || '-' });

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      cache: 'no-store',
      body: JSON.stringify({ command, speed: Number(speed) || 0 }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`status=${response.status}`);
        }
        debugEvent('send-ok', { command, speed, source: desiredSource || '-' });
      })
      .catch((error) => {
        debugEvent('send-fail', { command, speed, source: desiredSource || '-', info: String(error) });
      })
      .finally(() => {
        sendInFlight = false;
      });
  }

  function sendStop() {
    debugEvent('stop-dispatch', { command: 'S', speed: 0, source: activeInputSource || '-' });
    queueDesiredCommand('S', 0, activeInputSource || '-', true);
    setTimeout(() => queueDesiredCommand('S', 0, activeInputSource || '-', true), 70);
  }

  function clearHoldInterval() {
    if (holdIntervalId !== null) {
      clearInterval(holdIntervalId);
      holdIntervalId = null;
    }
  }

  function startHold(command, source = 'pointer') {
    if (command === 'S') {
      stopHold();
      return;
    }

    if (activeCommand === command && activeInputSource === source) {
      return;
    }

    activeCommand = command;
    activeInputSource = source;
    debugEvent('hold-start', { command, speed: getEffectiveSpeed(), source });
    window.__alphabotDriving = true;
    queueDesiredCommand(activeCommand, getEffectiveSpeed(), source, true);
    clearHoldInterval();

    holdIntervalId = setInterval(() => {
      if (!activeCommand) {
        return;
      }
      queueDesiredCommand(activeCommand, getEffectiveSpeed(), source);
    }, HOLD_INTERVAL_MS);
  }

  function stopHold() {
    debugEvent('hold-stop', { command: activeCommand || '-', speed: getEffectiveSpeed(), source: activeInputSource || '-' });
    activeCommand = null;
    activeInputSource = null;
    window.__alphabotDriving = false;
    clearHoldInterval();
    sendStop();
  }

  function updateKeyboardDrive() {
    const lastKey = pressedMovementKeys.length > 0
      ? pressedMovementKeys[pressedMovementKeys.length - 1]
      : null;

    if (!lastKey) {
      if (activeInputSource === 'keyboard') {
        stopHold();
      }
      return;
    }

    const command = KEY_TO_COMMAND[lastKey];
    if (command) {
      startHold(command, 'keyboard');
    }
  }

  function bindHold(buttonId, command) {
    const button = document.getElementById(buttonId);
    if (!button || button.dataset.holdBound === '1') {
      return;
    }

    button.dataset.holdBound = '1';

    const start = (event) => {
      event.preventDefault();
      startHold(command, 'pointer');
    };

    const stop = (event) => {
      event.preventDefault();
      stopHold();
    };

    button.addEventListener('mousedown', start);
    button.addEventListener('touchstart', start, { passive: false });

    button.addEventListener('mouseup', stop);
    button.addEventListener('mouseleave', stop);
    button.addEventListener('touchend', stop, { passive: false });
    button.addEventListener('touchcancel', stop, { passive: false });
  }

  function isTypingTarget(target) {
    if (!target) return false;
    const tagName = (target.tagName || '').toLowerCase();
    return (
      tagName === 'input' ||
      tagName === 'textarea' ||
      tagName === 'select' ||
      target.isContentEditable
    );
  }

  function bindKeyboardControls() {
    if (window.__alphabotKeyboardBound) {
      return;
    }
    window.__alphabotKeyboardBound = true;

    window.addEventListener('keydown', (event) => {
      if (isTypingTarget(event.target)) {
        return;
      }

      const key = event.key.toLowerCase();

      if (key === 'shift') {
        precisionMode = true;
        debugEvent('key-shift-down', { source: 'keyboard' });
        if (activeCommand) {
          queueDesiredCommand(activeCommand, getEffectiveSpeed(), 'keyboard', true);
        }
        return;
      }

      if (key === ' ' || key === 'x') {
        event.preventDefault();
        debugEvent('key-stop', { source: 'keyboard' });
        pressedMovementKeys = [];
        stopHold();
        return;
      }

      const command = KEY_TO_COMMAND[key];
      if (!command) {
        return;
      }

      event.preventDefault();
      debugEvent('key-down', { command, source: 'keyboard', info: key });
      if (!pressedMovementKeys.includes(key)) {
        pressedMovementKeys.push(key);
      }
      updateKeyboardDrive();
    });

    window.addEventListener('keyup', (event) => {
      const key = event.key.toLowerCase();

      if (key === 'shift') {
        precisionMode = false;
        debugEvent('key-shift-up', { source: 'keyboard' });
        if (activeCommand) {
          queueDesiredCommand(activeCommand, getEffectiveSpeed(), 'keyboard', true);
        }
        return;
      }

      if (key === ' ' || key === 'x') {
        return;
      }

      const command = KEY_TO_COMMAND[key];
      if (!command) {
        return;
      }

      const keyIndex = pressedMovementKeys.indexOf(key);
      if (keyIndex !== -1) {
        pressedMovementKeys.splice(keyIndex, 1);
      }

      debugEvent('key-up', { command, source: 'keyboard', info: key });

      updateKeyboardDrive();
    });

    window.addEventListener('blur', () => {
      debugEvent('window-blur', { source: 'keyboard' });
      precisionMode = false;
      pressedMovementKeys = [];
      if (activeInputSource === 'keyboard') {
        stopHold();
      }
    });
  }

  function bindSpeedLiveUpdate() {
    const speedInput = document.getElementById('speed-input');
    if (!speedInput || speedInput.dataset.speedBound === '1') {
      return;
    }

    speedInput.dataset.speedBound = '1';

    const onSpeedChange = () => {
      if (activeCommand) {
        queueDesiredCommand(activeCommand, getEffectiveSpeed(), activeInputSource || '-', true);
      }
    };

    speedInput.addEventListener('input', onSpeedChange);
    speedInput.addEventListener('change', onSpeedChange);
  }

  function initBindings() {
    bindHold('btn-f', 'F');
    bindHold('btn-b', 'B');
    bindHold('btn-l', 'L');
    bindHold('btn-r', 'R');
    bindHold('btn-s', 'S');
    bindSpeedLiveUpdate();
    bindKeyboardControls();

    if (!window.__alphabotGlobalStopBound) {
      window.__alphabotGlobalStopBound = true;
      window.addEventListener('mouseup', stopHold);
      window.addEventListener('touchend', stopHold, { passive: true });
      window.addEventListener('blur', stopHold);
    }
  }

  const observer = new MutationObserver(initBindings);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBindings);
  } else {
    initBindings();
  }
})();
