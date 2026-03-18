(function () {
  const SNAPSHOT_IDLE_MS = 140;
  const SNAPSHOT_DRIVING_MS = 280;
  const STREAM_RETRY_MS = 3000;
  let snapshotTimer = null;
  let frameInFlight = false;
  let fallbackActive = false;
  let lastStreamAttemptAt = 0;

  function getBotIp() {
    const ipNode = document.getElementById('bot-ip');
    return ipNode ? ipNode.textContent.trim() : null;
  }

  function getCameraNode() {
    return document.getElementById('camera-feed');
  }

  function getStatusNode() {
    return document.getElementById('camera-status');
  }

  function setCameraStatus(text, color = '#90caf9') {
    const statusNode = getStatusNode();
    if (!statusNode) return;
    statusNode.textContent = text;
    statusNode.style.color = color;
  }

  function streamUrl(botIp) {
    return `http://${botIp}:81/stream`;
  }

  function captureUrl(botIp) {
    return `http://${botIp}/capture?t=${Date.now()}`;
  }

  function stopSnapshotMode() {
    if (snapshotTimer !== null) {
      clearTimeout(snapshotTimer);
      snapshotTimer = null;
    }
  }

  function startSnapshotMode(img, botIp) {
    if (!img || !botIp || snapshotTimer !== null) {
      return;
    }

    fallbackActive = true;
    setCameraStatus('Kamera: FALLBACK aktiv (/capture)', '#ffb74d');

    img.addEventListener('load', () => {
      frameInFlight = false;
    });

    img.addEventListener('error', () => {
      frameInFlight = false;
    });

    const updateSnapshot = () => {
      if (!fallbackActive) {
        return;
      }

      if (frameInFlight) {
        return;
      }

      frameInFlight = true;
      img.src = captureUrl(botIp);
    };

    const scheduleNext = () => {
      if (!fallbackActive) {
        stopSnapshotMode();
        return;
      }

      const now = Date.now();
      if (now - lastStreamAttemptAt > STREAM_RETRY_MS) {
        lastStreamAttemptAt = now;
        setCameraStatus('Kamera: versuche Rückkehr zu STREAM...', '#90caf9');
        img.src = streamUrl(botIp);
        return;
      }

      const nextDelay = window.__alphabotDriving ? SNAPSHOT_DRIVING_MS : SNAPSHOT_IDLE_MS;
      snapshotTimer = setTimeout(() => {
        if (!document.body.contains(img)) {
          stopSnapshotMode();
          return;
        }

        updateSnapshot();
        scheduleNext();
      }, nextDelay);
    };

    updateSnapshot();
    scheduleNext();
  }

  function initCameraFallback() {
    const img = getCameraNode();
    const botIp = getBotIp();
    if (!img || !botIp || img.dataset.cameraFallbackBound === '1') {
      return;
    }

    img.dataset.cameraFallbackBound = '1';
    setCameraStatus('Kamera: stream wird initialisiert...', '#90caf9');

    img.addEventListener('error', () => {
      if (img.src.includes(':81/stream')) {
        setCameraStatus('Kamera: Stream-Error, nutze Fallback (/capture)', '#ffb74d');
        startSnapshotMode(img, botIp);
      } else {
        setCameraStatus('Kamera: Capture-Error, retry...', '#ef9a9a');
        startSnapshotMode(img, botIp);
      }
    });

    img.addEventListener('load', () => {
      if (img.src.includes(':81/stream')) {
        fallbackActive = false;
        stopSnapshotMode();
        setCameraStatus('Kamera: STREAM OK (:81/stream)', '#00e676');
      } else {
        setCameraStatus('Kamera: FALLBACK Frame OK (/capture)', '#ffb74d');
      }
    });

    img.src = streamUrl(botIp);
  }

  const observer = new MutationObserver(initCameraFallback);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCameraFallback);
  } else {
    initCameraFallback();
  }
})();
