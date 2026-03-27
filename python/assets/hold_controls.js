(function () {
  const HOLD_INTERVAL_MS = 120;
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
    const clamped = Math.max(58, Math.min(255, speed));
    if (!precisionMode) {
      return clamped;
    }
    return Math.max(58, Math.round(clamped * PRECISION_FACTOR));
  }

  function sendMotorCommand(command, speed, retries = 0) {
    const botIp = getBotIp();
    if (!botIp || botIp === '192.168.x.x') {
      return;
    }

    const now = Date.now();
    if (
      retries === 0 &&
      command === lastSentCommand &&
      speed === lastSentSpeed &&
      now - lastSentAtMs < MIN_SEND_GAP_MS
    ) {
      return;
    }

    const url = `http://${botIp}/cmd?p=M${command}${speed}`;
    const trySend = (attempt) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 120);

      lastSentCommand = command;
      lastSentSpeed = speed;
      lastSentAtMs = Date.now();

      fetch(url, { cache: 'no-store', signal: controller.signal })
        .catch(() => {
          if (attempt < retries) {
            setTimeout(() => trySend(attempt + 1), 70);
          }
        })
        .finally(() => {
          clearTimeout(timer);
        });
    };

    trySend(0);
  }

  function sendStop() {
    sendMotorCommand('S', '0', 2);
    setTimeout(() => sendMotorCommand('S', '0', 1), 60);
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
    window.__alphabotDriving = true;
    sendMotorCommand(activeCommand, getEffectiveSpeed());
    clearHoldInterval();

    holdIntervalId = setInterval(() => {
      if (!activeCommand) {
        return;
      }
      sendMotorCommand(activeCommand, getEffectiveSpeed());
    }, HOLD_INTERVAL_MS);
  }

  function stopHold() {
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
        if (activeCommand) {
          sendMotorCommand(activeCommand, getEffectiveSpeed());
        }
        return;
      }

      if (key === ' ' || key === 'x') {
        event.preventDefault();
        pressedMovementKeys = [];
        stopHold();
        return;
      }

      const command = KEY_TO_COMMAND[key];
      if (!command) {
        return;
      }

      event.preventDefault();
      if (!pressedMovementKeys.includes(key)) {
        pressedMovementKeys.push(key);
      }
      updateKeyboardDrive();
    });

    window.addEventListener('keyup', (event) => {
      const key = event.key.toLowerCase();

      if (key === 'shift') {
        precisionMode = false;
        if (activeCommand) {
          sendMotorCommand(activeCommand, getEffectiveSpeed());
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

      updateKeyboardDrive();
    });

    window.addEventListener('blur', () => {
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
        sendMotorCommand(activeCommand, getEffectiveSpeed());
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
