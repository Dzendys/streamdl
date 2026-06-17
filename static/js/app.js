const form = document.getElementById('downloadForm');
const urlInput = document.getElementById('url');
const pasteBtn = document.getElementById('pasteBtn');
const urlBadge = document.getElementById('urlBadge');

// Hidden inputs
const hiddenDownloadMode = document.getElementById('hiddenDownloadMode');
const hiddenVideoQuality = document.getElementById('hiddenVideoQuality');
const hiddenAudioBitrate = document.getElementById('hiddenAudioBitrate');

// UI selectors
const modeCards = document.querySelectorAll('.mode-card');
const qualityCards = document.querySelectorAll('.quality-card:not([data-audio-bitrate])');
const audioCards = document.querySelectorAll('[data-audio-bitrate]');
const qualitySection = document.getElementById('qualitySection');
const audioSection = document.getElementById('audioSection');
const submitBtn = document.getElementById('submitBtn');

// Mode Selector Handler
modeCards.forEach(card => {
    card.addEventListener('click', () => {
        // Deactivate all
        modeCards.forEach(c => c.classList.remove('active'));
        // Activate current
        card.classList.add('active');
        
        const mode = card.dataset.mode;
        hiddenDownloadMode.value = mode;

        // Show/Hide quality sections
        if (mode === 'audio') {
            qualitySection.classList.add('hidden');
            audioSection.classList.remove('hidden');
        } else {
            qualitySection.classList.remove('hidden');
            audioSection.classList.add('hidden');
        }
    });
});

// Video Quality Selector Handler
qualityCards.forEach(card => {
    card.addEventListener('click', () => {
        qualityCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        
        const quality = card.dataset.quality;
        hiddenVideoQuality.value = quality;
    });
});

// Audio Quality Selector Handler
audioCards.forEach(card => {
    card.addEventListener('click', () => {
        audioCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        
        const bitrate = card.dataset.audioBitrate;
        hiddenAudioBitrate.value = bitrate;
    });
});

// URL change detection & badges
let lastUrl = '';
let infoTimeout = null;
let videoDurationSeconds = 0;

urlInput.addEventListener('input', () => {
    const val = urlInput.value.trim();
    const lowerVal = val.toLowerCase();
    
    if (lowerVal.includes('youtube.com') || lowerVal.includes('youtu.be')) {
        urlBadge.textContent = 'YouTube';
        urlBadge.style.color = '#ef4444';
        urlBadge.style.background = 'rgba(239, 68, 68, 0.12)';
        urlBadge.style.borderColor = 'rgba(239, 68, 68, 0.25)';
        urlBadge.classList.add('active');
    } else if (lowerVal.includes('tiktok.com')) {
        urlBadge.textContent = 'TikTok';
        urlBadge.style.color = '#2dd4bf';
        urlBadge.style.background = 'rgba(45, 212, 191, 0.12)';
        urlBadge.style.borderColor = 'rgba(45, 212, 191, 0.25)';
        urlBadge.classList.add('active');
    } else if (lowerVal.includes('vimeo.com')) {
        urlBadge.textContent = 'Vimeo';
        urlBadge.style.color = '#38bdf8';
        urlBadge.style.background = 'rgba(56, 189, 248, 0.12)';
        urlBadge.style.borderColor = 'rgba(56, 189, 248, 0.25)';
        urlBadge.classList.add('active');
    } else if (val.length > 5) {
        urlBadge.textContent = 'Ostatní';
        urlBadge.style.color = '#a78bfa';
        urlBadge.style.background = 'rgba(167, 139, 250, 0.12)';
        urlBadge.style.borderColor = 'rgba(167, 139, 250, 0.25)';
        urlBadge.classList.add('active');
    } else {
        urlBadge.classList.remove('active');
    }

    // Debounce info loading
    clearTimeout(infoTimeout);
    if (val.startsWith('http://') || val.startsWith('https://')) {
        infoTimeout = setTimeout(() => {
            fetchVideoInfo(val);
        }, 600);
    }
});

// Clipboard Paste Button Helper
pasteBtn.addEventListener('click', async () => {
    try {
        const text = await navigator.clipboard.readText();
        urlInput.value = text;
        urlInput.dispatchEvent(new Event('input'));
        fetchVideoInfo(text);
    } catch (err) {
        urlInput.focus();
    }
});

// Format bytes to readable size
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    if (!bytes || bytes < 0) return 'Neznámá velikost';
    if (bytes < 1024) return bytes.toFixed(1) + ' B';
    const k = 1024;
    const dm = 1;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const idx = Math.min(i, sizes.length - 1);
    return parseFloat((bytes / Math.pow(k, idx)).toFixed(dm)) + ' ' + sizes[idx];
}

// Audio sizes calculations based on bitrate and duration
function updateAudioSizes() {
    const bitrates = [320, 256, 192, 128];
    bitrates.forEach(br => {
        const bytes = (br * 1000 / 8) * videoDurationSeconds;
        const descEl = document.getElementById(`desc-audio-${br}`);
        if (descEl) {
            const descText = descEl.getAttribute('data-original-desc');
            descEl.innerHTML = `${descText} &bull; <strong style="color: #a855f7;">${formatBytes(bytes)}</strong>`;
        }
    });
}

// Fetch video info metadata & size estimates
async function fetchVideoInfo(url) {
    if (!url || url === lastUrl) return;
    lastUrl = url;

    const infoSkeleton = document.getElementById('infoSkeleton');
    const infoPanel = document.getElementById('infoPanel');
    
    infoSkeleton.style.display = 'flex';
    infoPanel.style.display = 'none';

    try {
        const formData = new FormData();
        formData.append('url', url);

        const res = await fetch('/api/info', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) throw new Error('Info fetch failed');
        const data = await res.json();

        // Store duration seconds
        const parts = data.duration.split(':').map(Number);
        if (parts.length === 3) {
            videoDurationSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
        } else if (parts.length === 2) {
            videoDurationSeconds = parts[0] * 60 + parts[1];
        } else {
            videoDurationSeconds = 0;
        }

        // Populate Info Panel
        document.getElementById('infoThumbnail').src = data.thumbnail;
        document.getElementById('infoTitle').textContent = data.title;
        document.getElementById('infoAuthor').textContent = data.uploader;
        document.getElementById('infoDuration').querySelector('span').textContent = data.duration;

        // Handle audio-only vs video sources dynamically
        const audioOnlyBadge = document.getElementById('audioOnlyBadge');
        const autoCard = document.querySelector('.mode-card[data-mode="auto"]');
        const muteCard = document.querySelector('.mode-card[data-mode="mute"]');
        const audioCard = document.querySelector('.mode-card[data-mode="audio"]');

        if (data.has_video === false) {
            if (audioOnlyBadge) audioOnlyBadge.style.display = 'inline-flex';
            
            // Disable video options
            if (autoCard) autoCard.classList.add('disabled');
            if (muteCard) muteCard.classList.add('disabled');
            
            // Switch select mode to audio
            modeCards.forEach(c => c.classList.remove('active'));
            if (audioCard) {
                audioCard.classList.add('active');
                hiddenDownloadMode.value = 'audio';
                qualitySection.classList.add('hidden');
                audioSection.classList.remove('hidden');
            }
        } else {
            if (audioOnlyBadge) audioOnlyBadge.style.display = 'none';
            
            // Enable video options
            if (autoCard) autoCard.classList.remove('disabled');
            if (muteCard) muteCard.classList.remove('disabled');
            
            // If it was switched to audio by force, switch it back to auto
            if (hiddenDownloadMode.value === 'audio') {
                modeCards.forEach(c => c.classList.remove('active'));
                if (autoCard) {
                    autoCard.classList.add('active');
                    hiddenDownloadMode.value = 'auto';
                    qualitySection.classList.remove('hidden');
                    audioSection.classList.add('hidden');
                }
            }
        }

        // Populate Video sizes
        window.fetchedSizes = data.sizes;

        document.getElementById('desc-max').innerHTML = `Maximální dostupná kvalita zdroje &bull; <strong style="color: #a855f7;">${formatBytes(data.sizes.max)}</strong>`;
        document.getElementById('desc-1080').innerHTML = `Standard pro většinu obrazovek &bull; <strong style="color: #a855f7;">${formatBytes(data.sizes['1080'])}</strong>`;
        document.getElementById('desc-720').innerHTML = `Vhodné pro menší velikost souboru &bull; <strong style="color: #a855f7;">${formatBytes(data.sizes['720'])}</strong>`;
        document.getElementById('desc-480').innerHTML = `Úsporný režim pro mobilní data &bull; <strong style="color: #a855f7;">${formatBytes(data.sizes['480'])}</strong>`;

        // Calculate and populate Audio sizes
        if (videoDurationSeconds > 0) {
            updateAudioSizes();
        }

        // Dynamic video quality cards enablement and badges
        const cardMax = document.querySelector('.quality-card[data-quality="max"]');
        const card1080 = document.querySelector('.quality-card[data-quality="1080"]');
        const card720 = document.querySelector('.quality-card[data-quality="720"]');
        const card480 = document.querySelector('.quality-card[data-quality="480"]');

        const nameMax = document.getElementById('name-max');
        const badgeMax = document.getElementById('badge-max');
        const badge1080 = document.getElementById('badge-1080');
        const badge720 = document.getElementById('badge-720');
        const badge480 = document.getElementById('badge-480');

        // Reset all states
        [card1080, card720, card480].forEach(c => {
            if (c) c.classList.remove('disabled');
        });
        if (nameMax) nameMax.textContent = '4K UHD';
        if (badgeMax) badgeMax.textContent = 'Nejlepší';
        if (badge1080) badge1080.textContent = 'Full HD';
        if (badge720) badge720.textContent = 'HD ready';
        if (badge480) badge480.textContent = 'SD rozlišení';

        if (data.has_video && data.max_height > 0) {
            const mh = data.max_height;
            
            // Update Max quality name to show the actual maximum resolution
            let maxLabel = '4K UHD';
            if (mh >= 2160) maxLabel = '4K UHD';
            else if (mh >= 1440) maxLabel = '2K QHD';
            else if (mh >= 1080) maxLabel = '1080p FHD';
            else if (mh >= 720) maxLabel = '720p HD';
            else maxLabel = mh + 'p';
            
            if (nameMax) nameMax.textContent = maxLabel;
            if (badgeMax) badgeMax.textContent = 'Nejlepší';

            // Disable cards that have higher resolution than the source video
            if (mh < 1080 && card1080) {
                card1080.classList.add('disabled');
                if (badge1080) badge1080.textContent = 'Nedostupné';
            }
            if (mh < 720 && card720) {
                card720.classList.add('disabled');
                if (badge720) badge720.textContent = 'Nedostupné';
            }
            if (mh < 360 && card480) {
                card480.classList.add('disabled');
                if (badge480) badge480.textContent = 'Nedostupné';
            }

            // If currently selected card became disabled, auto-select "max" card
            const activeVideoCard = document.querySelector('.quality-card.active:not([data-audio-bitrate])');
            if (activeVideoCard && activeVideoCard.classList.contains('disabled')) {
                qualityCards.forEach(c => c.classList.remove('active'));
                if (cardMax) {
                    cardMax.classList.add('active');
                    hiddenVideoQuality.value = 'max';
                }
            }
        }

        infoSkeleton.style.display = 'none';
        infoPanel.style.display = 'flex';
    } catch (err) {
        console.error(err);
        infoSkeleton.style.display = 'none';
        infoPanel.style.display = 'none';
    }
}

// Form submission animation handling and streaming download progress
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;
    
    const statusPanel = document.getElementById('statusPanel');
    const downloadManager = document.getElementById('downloadManager');
    const dot1 = document.getElementById('dot1');
    const dot2 = document.getElementById('dot2');
    const dot3 = document.getElementById('dot3');
    const step2 = document.getElementById('step2');
    const step3 = document.getElementById('step3');
    const progressBarFill = document.getElementById('progressBarFill');
    const cancelBtn = document.getElementById('cancelBtn');
    const cancelBtnStatus = document.getElementById('cancelBtnStatus');
    
    // Reset checkmarks text content
    dot1.innerHTML = '';
    dot2.innerHTML = '';
    dot3.innerHTML = '';
    
    // Show status panel and reset states
    statusPanel.style.display = 'flex';
    downloadManager.style.display = 'none';
    dot1.className = 'status-dot active';
    dot2.className = 'status-dot';
    dot3.className = 'status-dot';
    step2.style.opacity = '0.5';
    step3.style.opacity = '0.5';
    
    // Setup AbortController for cancel button
    const downloadController = new AbortController();
    const signal = downloadController.signal;
    
    const onCancel = () => {
        downloadController.abort();
    };
    cancelBtn.addEventListener('click', onCancel);
    if (cancelBtnStatus) {
        cancelBtnStatus.addEventListener('click', onCancel);
    }
    
    // Animate progress bar
    let progress = 0;
    function setProgress(target) {
        progress = target;
        progressBarFill.style.width = progress + '%';
    }
    
    setProgress(5);
    
    // Step 1 -> Step 2
    setTimeout(() => {
        if (signal.aborted) return;
        dot1.className = 'status-dot done';
        dot1.innerHTML = '✓';
        dot1.style.color = '#ffffff';
        dot1.style.fontSize = '0.65rem';
        dot1.style.fontWeight = 'bold';
        
        dot2.className = 'status-dot active';
        step2.style.opacity = '1';
        setProgress(35);
    }, 1500);

    try {
        const formData = new FormData(form);
        const response = await fetch('/api/download', {
            method: 'POST',
            body: formData,
            signal: signal
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || 'Stahování selhalo. Zkontrolujte odkaz.');
        }

        // Step 2 -> Step 3
        dot2.className = 'status-dot done';
        dot2.innerHTML = '✓';
        dot2.style.color = '#ffffff';
        dot2.style.fontSize = '0.65rem';
        dot2.style.fontWeight = 'bold';
        
        dot3.className = 'status-dot active';
        step3.style.opacity = '1';
        setProgress(70);

        // Display Download Manager and hide preparation panel
        statusPanel.style.display = 'none';
        downloadManager.style.display = 'block';

        // Extract filename
        let filename = 'media.mp4';
        const disposition = response.headers.get('content-disposition');
        if (disposition && disposition.indexOf('filename=') !== -1) {
            const matches = disposition.match(/filename="([^"]+)"/);
            if (matches && matches[1]) {
                filename = decodeURIComponent(matches[1]);
            }
        }
        document.getElementById('managerFilename').textContent = filename;

        // Determine size
        let totalBytes = parseInt(response.headers.get('content-length'));
        if (isNaN(totalBytes) || totalBytes <= 0) {
            const mode = hiddenDownloadMode.value;
            const quality = hiddenVideoQuality.value;
            const br = hiddenAudioBitrate.value;
            
            if (mode === 'audio' && videoDurationSeconds > 0) {
                totalBytes = (br * 1000 / 8) * videoDurationSeconds;
            } else if (window.fetchedSizes) {
                totalBytes = window.fetchedSizes[quality] || 0;
            }
        }

        // Stream Reader
        const reader = response.body.getReader();
        const chunks = [];
        let loadedBytes = 0;
        const startTime = performance.now();

        const managerPercent = document.getElementById('managerPercent');
        const managerBarFill = document.getElementById('managerBarFill');
        const managerBytes = document.getElementById('managerBytes');
        const managerSpeed = document.getElementById('managerSpeed');
        const managerRemaining = document.getElementById('managerRemaining');

        while (true) {
            if (signal.aborted) {
                throw new DOMException('The user aborted a request.', 'AbortError');
            }
            const { done, value } = await reader.read();
            if (done) break;

            chunks.push(value);
            loadedBytes += value.length;

            const percent = totalBytes > 0 ? Math.min(Math.round((loadedBytes / totalBytes) * 100), 99) : 0;
            const elapsed = (performance.now() - startTime) / 1000;
            const speed = elapsed > 0 ? loadedBytes / elapsed : 0;

            managerPercent.textContent = totalBytes > 0 ? percent + '%' : 'Načítání...';
            managerBarFill.style.width = totalBytes > 0 ? percent + '%' : '50%';
            managerBytes.textContent = `${formatBytes(loadedBytes)} / ${totalBytes > 0 ? formatBytes(totalBytes) : 'Neznámá velikost'}`;
            managerSpeed.textContent = formatBytes(speed) + '/s';

            if (totalBytes > 0 && speed > 0) {
                const remaining = Math.max(0, (totalBytes - loadedBytes) / speed);
                const remMin = Math.floor(remaining / 60);
                const remSec = Math.floor(remaining % 60);
                managerRemaining.textContent = `Zbývá ${remMin}:${remSec.toString().padStart(2, '0')}`;
            } else {
                managerRemaining.textContent = 'Zbývá --:--';
            }
        }

        // Finished
        setProgress(100);
        dot3.className = 'status-dot done';
        dot3.innerHTML = '✓';
        dot3.style.color = '#ffffff';
        dot3.style.fontSize = '0.65rem';
        dot3.style.fontWeight = 'bold';

        managerPercent.textContent = '100%';
        managerBarFill.style.width = '100%';
        managerRemaining.textContent = 'Staženo';

        // Clean up cancel listener
        cancelBtn.removeEventListener('click', onCancel);
        cancelBtn.style.display = 'none';
        if (cancelBtnStatus) {
            cancelBtnStatus.removeEventListener('click', onCancel);
            cancelBtnStatus.style.display = 'none';
        }

        // Trigger Save
        const blob = new Blob(chunks, { type: response.headers.get('content-type') || 'application/octet-stream' });
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);

        setTimeout(() => {
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
            statusPanel.style.display = 'none';
            downloadManager.style.display = 'none';
            
            // Restore button displays for the next download
            cancelBtn.style.display = 'flex';
            if (cancelBtnStatus) {
                cancelBtnStatus.style.display = 'flex';
            }
        }, 3000);

    } catch (err) {
        cancelBtn.removeEventListener('click', onCancel);
        if (cancelBtnStatus) {
            cancelBtnStatus.removeEventListener('click', onCancel);
        }
        
        if (err.name === 'AbortError') {
            // Handle cancellation gently
            submitBtn.classList.remove('loading');
            submitBtn.disabled = false;
            statusPanel.style.display = 'none';
            downloadManager.style.display = 'none';
            return;
        }
        
        console.error(err);
        alert(err.message || 'Při stahování nastala chyba.');
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
        statusPanel.style.display = 'none';
        downloadManager.style.display = 'none';
    }
});

// Fetch and display yt-dlp version
async function loadYtdlpVersion() {
    try {
        const res = await fetch('/api/yt-dlp/version');
        if (res.ok) {
            const data = await res.json();
            document.getElementById('ytdlpVersionBadge').textContent = `yt-dlp: ${data.version}`;
        }
    } catch (err) {
        console.error('Failed to load yt-dlp version', err);
    }
}

// Manual update handler
const updateYtdlpBtn = document.getElementById('updateYtdlpBtn');
if (updateYtdlpBtn) {
    updateYtdlpBtn.addEventListener('click', async () => {
        updateYtdlpBtn.disabled = true;
        const btnText = updateYtdlpBtn.querySelector('span');
        const icon = updateYtdlpBtn.querySelector('.update-icon');
        
        btnText.textContent = 'Aktualizuji...';
        if (icon) icon.classList.add('spinning');
        
        try {
            const res = await fetch('/api/yt-dlp/update', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                alert(`Aktualizace úspěšná! Nová verze: ${data.version}`);
                document.getElementById('ytdlpVersionBadge').textContent = `yt-dlp: ${data.version}`;
            } else {
                alert(`Aktualizace selhala: ${data.message}`);
            }
        } catch (err) {
            console.error(err);
            alert('Chyba při komunikaci se serverem.');
        } finally {
            btnText.textContent = 'Aktualizovat yt-dlp';
            if (icon) icon.classList.remove('spinning');
            updateYtdlpBtn.disabled = false;
        }
    });
}

// Load version on page load
loadYtdlpVersion();
