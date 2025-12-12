// Configuration - Update this with your backend URL
const BACKEND_URL = 'https://resalehub.onrender.com'; // Change to your backend URL

// DOM elements
const pairingCodeInput = document.getElementById('pairingCode');
const syncButton = document.getElementById('syncButton');
const statusDiv = document.getElementById('status');

// Format input to only allow 6 digits
pairingCodeInput.addEventListener('input', (e) => {
  e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6);
  syncButton.disabled = e.target.value.length !== 6;
});

// Allow Enter key to trigger sync
pairingCodeInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter' && pairingCodeInput.value.length === 6) {
    syncCookies();
  }
});

// Sync button click handler
syncButton.addEventListener('click', syncCookies);

async function syncCookies() {
  const pairingCode = pairingCodeInput.value.trim();
  
  if (pairingCode.length !== 6) {
    showStatus('Please enter a valid 6-digit code', 'error');
    return;
  }
  
  // Disable button and show loading
  syncButton.disabled = true;
  syncButton.textContent = 'Syncing...';
  hideStatus();
  
  try {
    // Step 1: Get all cookies from poshmark.com
    const cookies = await chrome.cookies.getAll({
      domain: 'poshmark.com'
    });
    
    if (!cookies || cookies.length === 0) {
      throw new Error('No cookies found. Please make sure you are logged into poshmark.com');
    }
    
    console.log(`Found ${cookies.length} cookies from poshmark.com`);
    
    // Step 2: Format cookies for backend
    const cookieData = cookies.map(cookie => ({
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      secure: cookie.secure,
      httpOnly: cookie.httpOnly,
      sameSite: cookie.sameSite,
      expirationDate: cookie.expirationDate
    }));
    
    // Step 3: Send to backend
    const response = await fetch(`${BACKEND_URL}/api/auth/sync-extension`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        pairing_code: pairingCode,
        cookies: cookieData
      })
    });
    
    const data = await response.json();
    
    if (!response.ok) {
      throw new Error(data.detail || data.message || `Server error: ${response.status}`);
    }
    
    // Success!
    showStatus('✓ Cookies synced successfully! You can close this window.', 'success');
    pairingCodeInput.value = '';
    syncButton.textContent = 'Sync Complete';
    
    // Auto-close after 2 seconds
    setTimeout(() => {
      window.close();
    }, 2000);
    
  } catch (error) {
    console.error('Sync error:', error);
    showStatus(`Error: ${error.message}`, 'error');
    syncButton.disabled = false;
    syncButton.textContent = 'Sync Poshmark Cookies';
  }
}

function showStatus(message, type) {
  statusDiv.textContent = message;
  statusDiv.className = `status ${type}`;
  statusDiv.style.display = 'block';
}

function hideStatus() {
  statusDiv.style.display = 'none';
}

// Initialize - check if we have a stored code
chrome.storage.local.get(['lastPairingCode'], (result) => {
  if (result.lastPairingCode) {
    pairingCodeInput.value = result.lastPairingCode;
    syncButton.disabled = false;
  }
});

// Store code when user types
pairingCodeInput.addEventListener('input', () => {
  if (pairingCodeInput.value.length === 6) {
    chrome.storage.local.set({ lastPairingCode: pairingCodeInput.value });
  }
});

