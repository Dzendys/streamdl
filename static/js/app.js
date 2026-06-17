const form = document.getElementById('downloadForm');
const urlInput = document.getElementById('url');
const pasteBtn = document.getElementById('pasteBtn');
const urlBadge = document.getElementById('urlBadge');

// Hidden inputs
const hiddenDownloadMode = document.getElementById('hiddenDownloadMode');
const hiddenVideoQuality = document.getElementById('hiddenVideoQuality');
const hiddenAudioBitrate = document.getElementById('hiddenAudioBitrate');

// UI selectors
const modeCards    = document.querySelectorAll('.mode-card');
const qualityCards = document.querySelectorAll('.quality-card:not([data-audio-bitrate])');
const audioCards   = document.querySelectorAll('[data-audio-bitrate]');
const qualitySection = document.getElementById('qualitySection');
const audioSection   = document.getElementById('audioSection');
const submitBtn      = document.getElementById('submitBtn');

// ── Mode Selector ──────────────────────────────────────────────────────────
modeCards.forEach(card => {
    card.addEventListener('click', () => {
        modeCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');

        const mode = card.dataset.mode;
        hiddenDownloadMode.value = mode;

        if (mode === 'audio') {
            qualitySection.classList.add('hidden');
            audioSection.classList.remove('hidden');
        } else {
            qualitySection.classList.remove('hidden');
            audioSection.classList.add('hidden');
        }
    });
});

// ── Video Quality Selector ─────────────────────────────────────────────────
qualityCards.forEach(card => {
    card.addEventListener('click', () => {
        qualityCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        hiddenVideoQuality.value = card.dataset.quality;
    });
});

// ── Audio Quality Selector ─────────────────────────────────────────────────
audioCards.forEach(card => {
    card.addEventListener('click', () => {
        audioCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        hiddenAudioBitrate.value = card.dataset.audioBitrate;
    });
});

// ── URL Detection & Badges ─────────────────────────────────────────────────
let lastUrl = '';
let infoTimeout = null;
let videoDurationSeconds = 0;

urlInput.addEventListener('input', () => {
    const val      = urlInput.value.trim();
    const lowerVal = val.toLowerCase();

    // Known audio-only platforms — hide concurrency slider immediately (no need to wait for API)
    const AUDIO_ONLY_DOMAINS = ['soundcloud.com'];
    const isKnownAudioOnly   = AUDIO_ONLY_DOMAINS.some(d => lowerVal.includes(d));
    const advancedSection    = document.querySelector('.advanced-section');
    if (advancedSection) advancedSection.style.display = isKnownAudioOnly ? 'none' : '';

    if (lowerVal.includes('youtube.com') || lowerVal.includes('youtu.be')) {
        urlBadge.textContent  = 'YouTube';
        urlBadge.style.color  = '#ef4444';
        urlBadge.style.background  = 'rgba(239, 68, 68, 0.12)';
        urlBadge.style.borderColor = 'rgba(239, 68, 68, 0.25)';
        urlBadge.classList.add('active');
    } else if (lowerVal.includes('tiktok.com')) {
        urlBadge.textContent  = 'TikTok';
        urlBadge.style.color  = '#2dd4bf';
        urlBadge.style.background  = 'rgba(45, 212, 191, 0.12)';
        urlBadge.style.borderColor = 'rgba(45, 212, 191, 0.25)';
        urlBadge.classList.add('active');
    } else if (lowerVal.includes('vimeo.com')) {
        urlBadge.textContent  = 'Vimeo';
        urlBadge.style.color  = '#38bdf8';
        urlBadge.style.background  = 'rgba(56, 189, 248, 0.12)';
        urlBadge.style.borderColor = 'rgba(56, 189, 248, 0.25)';
        urlBadge.classList.add('active');
    } else if (lowerVal.includes('soundcloud.com')) {
        urlBadge.textContent  = 'SoundCloud';
        urlBadge.style.color  = '#f97316';
        urlBadge.style.background  = 'rgba(249, 115, 22, 0.12)';
        urlBadge.style.borderColor = 'rgba(249, 115, 22, 0.25)';
        urlBadge.classList.add('active');
    } else if (val.length > 5) {
        urlBadge.textContent  = 'Ostatní';
        urlBadge.style.color  = '#a78bfa';
        urlBadge.style.background  = 'rgba(167, 139, 250, 0.12)';
        urlBadge.style.borderColor = 'rgba(167, 139, 250, 0.25)';
        urlBadge.classList.add('active');
    } else {
        urlBadge.classList.remove('active');
    }

    clearTimeout(infoTimeout);
    if (val.startsWith('http://') || val.startsWith('https://')) {
        infoTimeout = setTimeout(() => fetchVideoInfo(val), 600);
    }
});

// ── Clipboard Paste ────────────────────────────────────────────────────────
pasteBtn.addEventListener('click', async () => {
    try {
        const text = await navigator.clipboard.readText();
        urlInput.value = text;
        urlInput.dispatchEvent(new Event('input'));
        fetchVideoInfo(text);
    } catch {
        urlInput.focus();
    }
});

// ── Utility: format bytes ─────────────────────────────────────────────────
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    if (!bytes || bytes < 0) return 'Neznámá velikost';
    if (bytes < 1024) return bytes.toFixed(1) + ' B';
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), sizes.length - 1);
    return parseFloat((bytes / Math.pow(1024, i)).toFixed(1)) + ' ' + sizes[i];
}

// ── Audio size estimates based on bitrate ──────────────────────────────────
function updateAudioSizes() {
    [320, 256, 192, 128].forEach(br => {
        const bytes  = (br * 1000 / 8) * videoDurationSeconds;
        const descEl = document.getElementById(`desc-audio-${br}`);
        if (descEl) {
            const orig = descEl.getAttribute('data-original-desc');
            descEl.innerHTML = `${orig} &bull; <strong style="color:#a855f7">${formatBytes(bytes)}</strong>`;
        }
    });
}

// ── Fetch video metadata & size estimates ──────────────────────────────────
async function fetchVideoInfo(url) {
    if (!url || url === lastUrl) return;
    lastUrl = url;

    const infoSkeleton = document.getElementById('infoSkeleton');
    const infoPanel    = document.getElementById('infoPanel');
    infoSkeleton.style.display = 'flex';
    infoPanel.style.display    = 'none';

    try {
        const formData = new FormData();
        formData.append('url', url);
        const res = await fetch('/api/info', { method: 'POST', body: formData });
        if (!res.ok) throw new Error('Info fetch failed');
        const data = await res.json();

        // Parse duration to seconds
        const parts = data.duration.split(':').map(Number);
        if (parts.length === 3)      videoDurationSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
        else if (parts.length === 2) videoDurationSeconds = parts[0] * 60 + parts[1];
        else                         videoDurationSeconds = 0;

        // Populate info panel
        document.getElementById('infoThumbnail').src = data.thumbnail;
        document.getElementById('infoTitle').textContent = data.title;
        document.getElementById('infoAuthor').textContent = data.uploader;
        document.getElementById('infoDuration').querySelector('span').textContent = data.duration;

        const audioOnlyBadge = document.getElementById('audioOnlyBadge');
        const autoCard  = document.querySelector('.mode-card[data-mode="auto"]');
        const muteCard  = document.querySelector('.mode-card[data-mode="mute"]');
        const audioCard = document.querySelector('.mode-card[data-mode="audio"]');
        const adv       = document.querySelector('.advanced-section');

        if (data.has_video === false) {
            if (audioOnlyBadge) audioOnlyBadge.style.display = 'inline-flex';
            if (autoCard)  autoCard.classList.add('disabled');
            if (muteCard)  muteCard.classList.add('disabled');
            modeCards.forEach(c => c.classList.remove('active'));
            if (audioCard) {
                audioCard.classList.add('active');
                hiddenDownloadMode.value = 'audio';
                qualitySection.classList.add('hidden');
                audioSection.classList.remove('hidden');
            }
            if (adv) adv.style.display = 'none'; // no concurrency benefit for audio-only
        } else {
            if (audioOnlyBadge) audioOnlyBadge.style.display = 'none';
            if (autoCard)  autoCard.classList.remove('disabled');
            if (muteCard)  muteCard.classList.remove('disabled');
            if (adv)       adv.style.display = '';
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

        // Populate size estimates
        window.fetchedSizes = data.sizes;
        document.getElementById('desc-max').innerHTML  = `Maximální dostupná kvalita zdroje &bull; <strong style="color:#a855f7">${formatBytes(data.sizes.max)}</strong>`;
        document.getElementById('desc-1080').innerHTML = `Standard pro většinu obrazovek &bull; <strong style="color:#a855f7">${formatBytes(data.sizes['1080'])}</strong>`;
        document.getElementById('desc-720').innerHTML  = `Vhodné pro menší velikost souboru &bull; <strong style="color:#a855f7">${formatBytes(data.sizes['720'])}</strong>`;
        document.getElementById('desc-480').innerHTML  = `Úsporný režim pro mobilní data &bull; <strong style="color:#a855f7">${formatBytes(data.sizes['480'])}</strong>`;
        if (videoDurationSeconds > 0) updateAudioSizes();

        // Dynamic quality card state based on source max resolution
        const cardMax  = document.querySelector('.quality-card[data-quality="max"]');
        const card1080 = document.querySelector('.quality-card[data-quality="1080"]');
        const card720  = document.querySelector('.quality-card[data-quality="720"]');
        const card480  = document.querySelector('.quality-card[data-quality="480"]');
        const nameMax  = document.getElementById('name-max');
        const badgeMax = document.getElementById('badge-max');
        const badge1080 = document.getElementById('badge-1080');
        const badge720  = document.getElementById('badge-720');
        const badge480  = document.getElementById('badge-480');

        [card1080, card720, card480].forEach(c => c && c.classList.remove('disabled'));
        if (nameMax)  nameMax.textContent  = '4K UHD';
        if (badgeMax) badgeMax.textContent = 'Nejlepší';
        if (badge1080) badge1080.textContent = 'Full HD';
        if (badge720)  badge720.textContent  = 'HD ready';
        if (badge480)  badge480.textContent  = 'SD rozlišení';

        if (data.has_video && data.max_height > 0) {
            const mh = data.max_height;
            if (nameMax) nameMax.textContent =
                mh >= 2160 ? '4K UHD' : mh >= 1440 ? '2K QHD' : mh >= 1080 ? '1080p FHD' : mh >= 720 ? '720p HD' : mh + 'p';

            if (mh < 1080 && card1080) { card1080.classList.add('disabled'); if (badge1080) badge1080.textContent = 'Nedostupné'; }
            if (mh < 720  && card720)  { card720.classList.add('disabled');  if (badge720)  badge720.textContent  = 'Nedostupné'; }
            if (mh < 360  && card480)  { card480.classList.add('disabled');  if (badge480)  badge480.textContent  = 'Nedostupné'; }

            const activeCard = document.querySelector('.quality-card.active:not([data-audio-bitrate])');
            if (activeCard && activeCard.classList.contains('disabled') && cardMax) {
                qualityCards.forEach(c => c.classList.remove('active'));
                cardMax.classList.add('active');
                hiddenVideoQuality.value = 'max';
            }
        }

        infoSkeleton.style.display = 'none';
        infoPanel.style.display    = 'flex';
    } catch (err) {
        console.error(err);
        infoSkeleton.style.display = 'none';
        infoPanel.style.display    = 'none';
    }
}

// ── Form Submission — two-phase SSE download with real-time progress ───────
form.addEventListener('submit', async (e) => {
    e.preventDefault();

    submitBtn.classList.add('loading');
    submitBtn.disabled = true;

    const statusPanel     = document.getElementById('statusPanel');
    const downloadManager = document.getElementById('downloadManager');
    const dot1  = document.getElementById('dot1');
    const dot2  = document.getElementById('dot2');
    const dot3  = document.getElementById('dot3');
    const step2 = document.getElementById('step2');
    const step3 = document.getElementById('step3');
    const progressBarFill  = document.getElementById('progressBarFill');
    const cancelBtn        = document.getElementById('cancelBtn');
    const cancelBtnStatus  = document.getElementById('cancelBtnStatus');
    const managerPercent   = document.getElementById('managerPercent');
    const managerBarFill   = document.getElementById('managerBarFill');
    const managerBytes     = document.getElementById('managerBytes');
    const managerSpeed     = document.getElementById('managerSpeed');
    const managerRemaining = document.getElementById('managerRemaining');
    const managerStatus    = document.querySelector('.manager-status');

    // Reset UI
    dot1.innerHTML = dot2.innerHTML = dot3.innerHTML = '';
    statusPanel.style.display    = 'flex';
    downloadManager.style.display = 'none';
    dot1.className = 'status-dot active';
    dot2.className = 'status-dot';
    dot3.className = 'status-dot';
    step2.style.opacity = '0.5';
    step3.style.opacity = '0.5';

    const ctrl   = new AbortController();
    const signal = ctrl.signal;
    let evtSource = null;

    const onCancel = () => {
        ctrl.abort();
        if (evtSource) { evtSource.close(); evtSource = null; }
    };
    cancelBtn.addEventListener('click', onCancel);
    if (cancelBtnStatus) cancelBtnStatus.addEventListener('click', onCancel);

    const setProgress = pct => { progressBarFill.style.width = pct + '%'; };
    setProgress(5);

    const resetBtn = () => {
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
        cancelBtn.style.display = 'flex';
        if (cancelBtnStatus) cancelBtnStatus.style.display = 'flex';
    };

    const markDone = dot => {
        dot.className = 'status-dot done';
        dot.innerHTML = '✓';
        dot.style.cssText = 'color:#fff;font-size:.65rem;font-weight:bold';
    };

    try {
        // ── Phase 1: start download job on server ─────────────────────────
        const formData = new FormData(form);
        const startRes = await fetch('/api/download/start', {
            method: 'POST',
            body: formData,
            signal,
        });

        if (!startRes.ok) {
            const err = await startRes.json().catch(() => ({}));
            throw new Error(err.detail || 'Stahování selhalo. Zkontrolujte odkaz.');
        }

        const { download_id } = await startRes.json();

        // ── Phase 2: SSE — real-time yt-dlp server download progress ──────
        markDone(dot1);
        dot2.className = 'status-dot active';
        step2.style.opacity = '1';
        setProgress(35);

        // Switch to download manager for live progress
        statusPanel.style.display    = 'none';
        downloadManager.style.display = 'block';
        if (managerStatus) managerStatus.textContent = 'Stahuji ze zdroje...';
        managerPercent.textContent   = '0%';
        managerBarFill.style.width   = '0%';
        managerBytes.textContent     = '0 B / ?';
        managerSpeed.textContent     = '';
        managerRemaining.textContent = 'Zbývá --:--';

        await new Promise((resolve, reject) => {
            if (signal.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }

            evtSource = new EventSource(`/api/download/${download_id}/events`);

            evtSource.onmessage = (evt) => {
                if (signal.aborted) {
                    evtSource.close();
                    reject(new DOMException('Aborted', 'AbortError'));
                    return;
                }

                let data;
                try { data = JSON.parse(evt.data); } catch { return; }

                if (data.type === 'progress') {
                    const pct = Math.round(data.percent);
                    managerPercent.textContent   = pct + '%';
                    managerBarFill.style.width   = pct + '%';
                    managerBytes.textContent     = `? / ${data.total || '?'}`;
                    managerSpeed.textContent     = data.speed || '';
                    managerRemaining.textContent = data.eta ? `Zbývá ${data.eta}` : 'Zbývá --:--';

                } else if (data.type === 'status') {
                    if (managerStatus) {
                        managerStatus.textContent =
                            data.phase === 'merging'    ? 'Slučuji video a audio...' :
                            data.phase === 'converting' ? 'Konvertuji na MP3...'     : 'Zpracovávám...';
                    }
                    managerPercent.textContent   = '100%';
                    managerBarFill.style.width   = '100%';
                    managerRemaining.textContent = 'Finalizuji...';

                } else if (data.type === 'done' || data.type === 'end') {
                    evtSource.close(); evtSource = null;
                    resolve();

                } else if (data.type === 'error') {
                    evtSource.close(); evtSource = null;
                    reject(new Error(data.message));
                }
            };

            evtSource.onerror = () => {
                if (evtSource) { evtSource.close(); evtSource = null; }
                resolve(); // SSE closes after sentinel — treat as success
            };
        });

        // ── Phase 3: fetch completed file and stream to browser ───────────
        markDone(dot2);
        dot3.className = 'status-dot active';
        step3.style.opacity = '1';

        if (managerStatus) managerStatus.textContent = 'Přenáším do prohlížeče...';
        managerPercent.textContent   = '0%';
        managerBarFill.style.width   = '0%';
        managerBytes.textContent     = '';
        managerSpeed.textContent     = '';
        managerRemaining.textContent = 'Zbývá --:--';

        const fileRes = await fetch(`/api/download/${download_id}/file`, { signal });
        if (!fileRes.ok) {
            const err = await fileRes.json().catch(() => ({}));
            throw new Error(err.detail || 'Soubor nelze stáhnout');
        }

        // Extract filename — handle both RFC 5987 and simple Content-Disposition formats
        let filename = 'media.mp4';
        const disposition = fileRes.headers.get('content-disposition');
        if (disposition) {
            const rfc5987 = disposition.match(/filename\*=(?:UTF-8|utf-8)''([^;\s]+)/);
            if (rfc5987?.[1]) {
                filename = decodeURIComponent(rfc5987[1]);
            } else {
                const simple = disposition.match(/filename="([^"]+)"/) || disposition.match(/filename=([^;\s]+)/);
                if (simple?.[1]) filename = decodeURIComponent(simple[1]);
            }
        }
        document.getElementById('managerFilename').textContent = filename;

        // Stream reader — shows real browser transfer speed and progress
        const totalBytes = parseInt(fileRes.headers.get('content-length')) || 0;
        const reader     = fileRes.body.getReader();
        const chunks     = [];
        let loadedBytes  = 0;
        const startTime  = performance.now();

        while (true) {
            if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
            const { done, value } = await reader.read();
            if (done) break;

            chunks.push(value);
            loadedBytes += value.length;

            const pct     = totalBytes > 0 ? Math.min(Math.round((loadedBytes / totalBytes) * 100), 99) : 50;
            const elapsed = (performance.now() - startTime) / 1000;
            const speed   = elapsed > 0 ? loadedBytes / elapsed : 0;

            managerPercent.textContent = totalBytes > 0 ? pct + '%' : 'Načítání...';
            managerBarFill.style.width = (totalBytes > 0 ? pct : 50) + '%';
            managerBytes.textContent   = `${formatBytes(loadedBytes)} / ${totalBytes > 0 ? formatBytes(totalBytes) : '?'}`;
            managerSpeed.textContent   = formatBytes(speed) + '/s';

            if (totalBytes > 0 && speed > 0) {
                const rem    = Math.max(0, (totalBytes - loadedBytes) / speed);
                const remMin = Math.floor(rem / 60);
                const remSec = Math.floor(rem % 60);
                managerRemaining.textContent = `Zbývá ${remMin}:${remSec.toString().padStart(2, '0')}`;
            }
        }

        // All done
        markDone(dot3);
        managerPercent.textContent   = '100%';
        managerBarFill.style.width   = '100%';
        managerRemaining.textContent = 'Staženo';

        // Trigger browser save dialog
        const blob    = new Blob(chunks, { type: fileRes.headers.get('content-type') || 'application/octet-stream' });
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl; a.download = filename;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);

        setTimeout(() => {
            resetBtn();
            statusPanel.style.display    = 'none';
            downloadManager.style.display = 'none';
            lastUrl = ''; // Force info panel refresh on next URL input
        }, 3000);

    } catch (err) {
        if (evtSource) { evtSource.close(); evtSource = null; }
        cancelBtn.removeEventListener('click', onCancel);
        if (cancelBtnStatus) cancelBtnStatus.removeEventListener('click', onCancel);

        if (err.name === 'AbortError') {
            resetBtn();
            statusPanel.style.display    = 'none';
            downloadManager.style.display = 'none';
            return;
        }

        console.error(err);
        alert(err.message || 'Při stahování nastala chyba.');
        resetBtn();
        statusPanel.style.display    = 'none';
        downloadManager.style.display = 'none';
    }
});

// ── yt-dlp version badge ───────────────────────────────────────────────────
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

// ── Manual yt-dlp update ───────────────────────────────────────────────────
const updateYtdlpBtn = document.getElementById('updateYtdlpBtn');
if (updateYtdlpBtn) {
    updateYtdlpBtn.addEventListener('click', async () => {
        updateYtdlpBtn.disabled = true;
        const btnText = updateYtdlpBtn.querySelector('span');
        const icon    = updateYtdlpBtn.querySelector('.update-icon');
        btnText.textContent = 'Aktualizuji...';
        if (icon) icon.classList.add('spinning');

        try {
            const res  = await fetch('/api/yt-dlp/update', { method: 'POST' });
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

// ── Concurrency slider ─────────────────────────────────────────────────────
const concurrencyRange  = document.getElementById('concurrencyRange');
const concurrencyValue  = document.getElementById('concurrencyValue');
const hiddenConcurrency = document.getElementById('hiddenConcurrency');

if (concurrencyRange && concurrencyValue && hiddenConcurrency) {
    concurrencyRange.addEventListener('input', () => {
        const val = concurrencyRange.value;
        concurrencyValue.textContent = val;
        hiddenConcurrency.value      = val;
    });
}

// ── Init ───────────────────────────────────────────────────────────────────
loadYtdlpVersion();
